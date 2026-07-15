#!/usr/bin/env python3
"""ccpick - interactive picker for Claude Code sessions across all projects.

Claude Code stores one JSONL transcript per session under
``~/.claude/projects/<encoded-project-dir>/<session-id>.jsonl``. The built-in
``claude --resume`` / ``/resume`` picker only lists sessions for the current
working directory. This tool scans every project, lets you fuzzy-filter and
pick a session interactively, then resumes it in its original directory.

Zero third-party dependencies: standard library only, works on Windows and
POSIX. Reads transcripts head+tail (never loads multi-MB files fully) and
caches parsed metadata by mtime+size so repeat launches are instant.
"""

import argparse
import codecs
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
TRASH_DIR = os.path.join(HOME, ".claude", "ccpick-trash")
CACHE_PATH = os.path.join(HOME, ".claude", "ccpick-cache.json")
CACHE_VERSION = 3

# How much of each transcript to read from each end. Titles/first-prompt/cwd
# live near the start; the latest ai-title and last timestamp live near the end.
HEAD_BYTES = 256 * 1024
TAIL_BYTES = 128 * 1024

# Cap the stored first-prompt so the cache file and per-keystroke filtering stay
# bounded regardless of how long the opening message was.
FIRST_PROMPT_MAX = 500

# User "messages" that are not real prompts (slash-command echoes, hook and
# harness injections, tool results). A prompt starting with one of these is skipped.
META_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-",
    "<system-reminder>",
    "<task-notification>",
    "<user-prompt-submit-hook>",
    "Caveat:",
)

SORT_MODES = ("recent", "oldest", "project", "title")

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_text(s):
    """Collapse whitespace and strip control characters from a display string."""
    if not s:
        return s
    return _CTRL_RE.sub(" ", s)


def reconfigure_streams():
    """Force UTF-8 output so emoji/CJK titles never raise UnicodeEncodeError on
    Windows (redirected pipes default to cp1252) or legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def extract_text(content):
    """Pull plain text out of a message ``content`` (str or list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if isinstance(t, str):
                    out.append(t)
        return "\n".join(out)
    return ""


def is_real_prompt(text):
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    for pref in META_PREFIXES:
        if s.startswith(pref):
            return False
    return True


def _absorb(meta, d):
    """Fold one transcript record into the accumulating metadata dict."""
    if not isinstance(d, dict):
        return
    t = d.get("type")
    ts = d.get("timestamp")
    if isinstance(ts, str):
        if meta["firstTs"] is None or ts < meta["firstTs"]:
            meta["firstTs"] = ts
        if meta["lastTs"] is None or ts > meta["lastTs"]:
            meta["lastTs"] = ts
    if isinstance(d.get("cwd"), str) and not meta["cwd"]:
        meta["cwd"] = d["cwd"]
    if isinstance(d.get("gitBranch"), str) and not meta["gitBranch"]:
        meta["gitBranch"] = d["gitBranch"]
    if d.get("version"):
        meta["version"] = d["version"]
    if t == "custom-title" and isinstance(d.get("customTitle"), str):
        meta["customTitle"] = clean_text(d["customTitle"])
    elif t == "ai-title" and isinstance(d.get("aiTitle"), str):
        # Tail is parsed after head, so this keeps the most recent auto-title.
        meta["aiTitle"] = clean_text(d["aiTitle"])
    elif t == "summary" and isinstance(d.get("summary"), str) and not meta["summary"]:
        meta["summary"] = clean_text(d["summary"])
    elif t == "user" and not d.get("isSidechain") and not meta["firstPrompt"]:
        msg = d.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        txt = extract_text(content)
        if is_real_prompt(txt):
            meta["firstPrompt"] = clean_text(" ".join(txt.split()))[:FIRST_PROMPT_MAX]


def _iter_json_lines(raw, drop_first=False):
    """Yield parsed JSON *objects* from a decoded byte blob, tolerating partial
    lines at either end (a head blob's last line and a tail blob's first line
    may be truncated at the byte boundary) and skipping non-object records."""
    text = raw.decode("utf-8", "replace")
    lines = text.split("\n")
    if drop_first and lines:
        lines = lines[1:]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            yield obj


def parse_session(path):
    size = os.path.getsize(path)
    meta = {
        "path": path,
        "sessionId": os.path.splitext(os.path.basename(path))[0],
        "cwd": None,
        "customTitle": None,
        "aiTitle": None,
        "summary": None,
        "firstPrompt": None,
        "gitBranch": None,
        "version": None,
        "firstTs": None,
        "lastTs": None,
        "size": size,
    }
    with open(path, "rb") as fb:
        head = fb.read(HEAD_BYTES)
        if size > HEAD_BYTES + TAIL_BYTES:
            # Big file: parse the two ends separately, skip the unread middle.
            fb.seek(-TAIL_BYTES, os.SEEK_END)
            tail = fb.read()
            for d in _iter_json_lines(head):
                _absorb(meta, d)
            for d in _iter_json_lines(tail, drop_first=True):
                _absorb(meta, d)
        else:
            # Small/medium file: head + remainder covers everything, so parse
            # it as one blob (no record split at the head boundary).
            rest = fb.read()
            for d in _iter_json_lines(head + rest):
                _absorb(meta, d)

    if not meta["cwd"]:
        meta["cwd"] = decode_project_dir(os.path.basename(os.path.dirname(path)))

    meta["title"] = (
        meta["customTitle"]
        or meta["aiTitle"]
        or meta["summary"]
        or (meta["firstPrompt"][:160] if meta["firstPrompt"] else None)
        or "(untitled)"
    )
    return meta


def decode_project_dir(name):
    """Best-effort reverse of Claude Code's project-dir encoding. Very lossy:
    the encoder replaces *every* non-alphanumeric character (dots, spaces,
    underscores, literal dashes, both slashes) with '-', so the original path
    cannot be reconstructed unambiguously. Used only when no cwd is recorded."""
    if len(name) >= 3 and name[1:3] == "--" and name[0].isalpha():
        return name[0] + ":\\" + name[3:].replace("-", "\\")
    return name.replace("-", os.sep)


# --------------------------------------------------------------------------- #
# Scan + cache
# --------------------------------------------------------------------------- #
def session_files():
    if not os.path.isdir(PROJECTS_DIR):
        return []
    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    # Exclude nested subagent/workflow transcripts; keep only top-level sessions.
    sep = os.sep
    return [f for f in files if (sep + "subagents" + sep) not in f]


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("v") == CACHE_VERSION:
            return data.get("entries", {})
    except (OSError, ValueError):
        pass
    return {}


def save_cache(entries):
    try:
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"v": CACHE_VERSION, "entries": entries}, fh)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def scan(refresh=False, progress=True):
    files = session_files()
    cache = {} if refresh else load_cache()
    new_cache = {}
    metas = []
    total = len(files)
    for i, path in enumerate(files):
        try:
            st = os.stat(path)
        except OSError:
            continue
        cached = cache.get(path)
        if (
            cached
            and cached.get("mtime") == st.st_mtime
            and cached.get("size") == st.st_size
        ):
            meta = cached["meta"]
        else:
            if progress and total > 40:
                sys.stderr.write(f"\rscanning sessions {i + 1}/{total}...")
                sys.stderr.flush()
            try:
                meta = parse_session(path)
            except Exception:
                # A single unreadable/atypical transcript must not abort the scan.
                continue
        new_cache[path] = {"mtime": st.st_mtime, "size": st.st_size, "meta": meta}
        metas.append(meta)
    if progress and total > 40:
        sys.stderr.write("\r" + " " * 40 + "\r")
        sys.stderr.flush()
    save_cache(new_cache)
    return metas


def sort_metas(metas, mode):
    if mode == "oldest":
        return sorted(metas, key=lambda m: m["lastTs"] or "")
    if mode == "project":
        return sorted(metas, key=lambda m: ((m["cwd"] or "").lower(), m["lastTs"] or ""))
    if mode == "title":
        return sorted(metas, key=lambda m: (m["title"] or "").lower())
    return sorted(metas, key=lambda m: m["lastTs"] or "", reverse=True)  # recent


# --------------------------------------------------------------------------- #
# Trash (soft delete / restore / purge)
# --------------------------------------------------------------------------- #
def _mirror_path(path, src_root, dst_root):
    """Map a session path from one root (PROJECTS_DIR or TRASH_DIR) to its
    mirrored location under the other, preserving the
    <encoded-project-dir>/<session-id>.jsonl structure."""
    rel = os.path.relpath(path, src_root)
    return os.path.join(dst_root, rel)


def trash_path_for(session_path):
    return _mirror_path(session_path, PROJECTS_DIR, TRASH_DIR)


def live_path_for(trash_session_path):
    return _mirror_path(trash_session_path, TRASH_DIR, PROJECTS_DIR)


def move_to_trash(session_path):
    """Soft-delete: move a live session's .jsonl into its mirrored trash
    location, stamping its mtime to now so retention can be measured from
    the filesystem alone (no separate manifest). Returns the trash path."""
    dst = trash_path_for(session_path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(session_path, dst)
    now = time.time()
    os.utime(dst, (now, now))
    return dst


def restore_from_trash(trash_session_path):
    """Move a trashed session back to its live location. Returns the live
    path."""
    dst = live_path_for(trash_session_path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(trash_session_path, dst)
    return dst


def purge_expired_trash(retention_days):
    """Permanently delete trashed sessions whose mtime is older than
    retention_days. Returns the number of files purged."""
    if not os.path.isdir(TRASH_DIR):
        return 0
    cutoff = time.time() - retention_days * 86400
    purged = 0
    for path in glob.glob(os.path.join(TRASH_DIR, "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                purged += 1
        except OSError:
            continue
    return purged


# --------------------------------------------------------------------------- #
# Fuzzy matching
# --------------------------------------------------------------------------- #
SEPARATORS = " /\\-_.:"
BOUNDARY_BONUS = 10
CONSECUTIVE_BONUS = 5


def _is_word_boundary(s, j):
    """True if position j in s starts a new 'word' -- position 0, or
    immediately preceded by a separator character."""
    return j == 0 or s[j - 1] in SEPARATORS


def fuzzy_score(token, haystack):
    """Optimal fuzzy subsequence alignment of ``token`` inside
    ``haystack`` (case-insensitive), fzf/Sublime-style: contiguous runs
    and word-boundary matches score better, gaps score worse. Returns
    ``(score, matched_indices)`` -- lower score is a better match,
    ``matched_indices`` are positions in ``haystack`` in ascending order,
    one per character of ``token`` -- or ``None`` if ``token``'s
    characters don't all appear, in order, somewhere in ``haystack``."""
    token = token.lower()
    haystack = haystack.lower()
    m, n = len(token), len(haystack)
    if m == 0:
        return (0, [])
    if m > n:
        return None

    # Cheap rejection: a plain left-to-right subsequence scan. Most
    # candidates fail this while the user is still typing, so the
    # expensive DP below only runs on sessions that can possibly match.
    scan = 0
    for ch in token:
        scan = haystack.find(ch, scan)
        if scan == -1:
            return None
        scan += 1

    UNREACHABLE = float("inf")
    # parent[i][j]: haystack index used for token[i - 1] in the best
    # alignment that matches token[i] at haystack index j.
    parent = [[-1] * n for _ in range(m)]
    row = [UNREACHABLE] * n
    for j in range(n):
        if haystack[j] == token[0]:
            bonus = BOUNDARY_BONUS if _is_word_boundary(haystack, j) else 0
            row[j] = j - bonus

    for i in range(1, m):
        new_row = [UNREACHABLE] * n
        # best_gap tracks min(row[j'] - j') for every j' < (current j - 1)
        # seen so far, so the "skip some characters" case can be evaluated
        # in O(1) per j instead of rescanning all earlier j' each time.
        best_gap = UNREACHABLE
        best_gap_idx = -1
        for j in range(1, n):
            prior = j - 1
            if row[prior] != UNREACHABLE:
                candidate = row[prior] - prior
                if candidate < best_gap:
                    best_gap, best_gap_idx = candidate, prior
            if haystack[j] != token[i]:
                continue
            bonus = BOUNDARY_BONUS if _is_word_boundary(haystack, j) else 0
            best_score, best_from = UNREACHABLE, -1
            if row[prior] != UNREACHABLE:
                best_score, best_from = row[prior] - CONSECUTIVE_BONUS, prior
            if best_gap != UNREACHABLE:
                gapped = best_gap + prior
                if gapped < best_score:
                    best_score, best_from = gapped, best_gap_idx
            new_row[j] = best_score - bonus
            parent[i][j] = best_from
        row = new_row

    best_j, best_score = -1, UNREACHABLE
    for j in range(n):
        if row[j] < best_score:
            best_score, best_j = row[j], j
    if best_j == -1:
        return None

    indices = [0] * m
    j = best_j
    for i in range(m - 1, -1, -1):
        indices[i] = j
        j = parent[i][j]
    return (best_score, indices)


# --------------------------------------------------------------------------- #
# Filtering + formatting
# --------------------------------------------------------------------------- #
def haystack(m):
    return " ".join(
        x for x in (m["title"], m["cwd"], m["gitBranch"], m["firstPrompt"]) if x
    ).lower()


def match(query, m):
    """Fuzzy token-AND match. Empty query matches everything. Returns a
    sort score (lower = better) or None if any token fails to fuzzy-match."""
    if not query:
        return 0
    h = haystack(m)
    total = 0
    for tok in query.lower().split():
        result = fuzzy_score(tok, h)
        if result is None:
            return None
        total += result[0]
    return total


def apply_filter(metas, query):
    if not query:
        return list(metas)
    scored = []
    for m in metas:
        s = match(query, m)
        if s is not None:
            scored.append((s, m))
    scored.sort(key=lambda x: x[0])
    return [m for _, m in scored]


def rel_time(iso):
    if not iso:
        return "   -"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "   ?"
    s = (datetime.now(timezone.utc) - dt).total_seconds()
    if s < 0:
        s = 0
    if s < 60:
        return f"{int(s)}s"
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    if s < 86400 * 30:
        return f"{int(s // 86400)}d"
    if s < 86400 * 365:
        return f"{int(s // (86400 * 30))}mo"
    return f"{int(s // (86400 * 365))}y"


def project_label(cwd):
    if not cwd:
        return "?"
    p = cwd.replace("/", "\\")
    if p.rstrip("\\").lower() == HOME.replace("/", "\\").rstrip("\\").lower():
        return "~"
    parts = [x for x in p.split("\\") if x]
    if not parts:
        return p
    if len(parts) >= 2:
        return parts[-2] + "\\" + parts[-1]
    return parts[-1]


def char_width(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1


def display_width(s):
    return sum(char_width(c) for c in s)


def clip_prefix(s, n):
    """Like clip(), but returns (chars, truncated): the list of original
    characters that fit within a display width of n cells (reserving room
    for an ellipsis when truncation is needed) and whether truncation
    occurred, instead of a single joined+ellipsized string. Lets callers
    color individual surviving characters before re-joining."""
    if s is None:
        s = ""
    if display_width(s) <= n:
        return list(s), False
    if n <= 1:
        return list(s[:1]), False
    out = []
    w = 0
    for ch in s:
        cw = char_width(ch)
        if w + cw > n - 1:
            break
        out.append(ch)
        w += cw
    return out, True


def clip(s, n):
    """Truncate to a terminal display width of ``n`` cells (accounting for
    wide/zero-width characters), appending an ellipsis when truncated."""
    chars, truncated = clip_prefix(s, n)
    return "".join(chars) + ("…" if truncated else "")


def pad(s, n):
    """Left-justify ``s`` to a display width of ``n`` cells."""
    s = clip(s, n)
    return s + " " * (n - display_width(s))


def colorize_title(title, rest_width, highlight_idxs):
    """Build the title fragment for a picker row within rest_width cells,
    wrapping characters whose original index is in highlight_idxs with
    BOLD+CYAN. Falls back to plain clip() output when there is nothing to
    highlight."""
    if not highlight_idxs:
        return clip(title, rest_width)
    chars, truncated = clip_prefix(title, rest_width)
    parts = []
    for i, ch in enumerate(chars):
        if i in highlight_idxs:
            parts.append(BOLD + CYAN + ch + RESET)
        else:
            parts.append(ch)
    if truncated:
        parts.append("…")
    return "".join(parts)


def title_highlights(query, title):
    """Union of matched character indices (in title) across every
    whitespace-separated query token, for rendering highlights. Returns an
    empty set when there is no query or no title."""
    if not query or not title:
        return set()
    idxs = set()
    for tok in query.lower().split():
        result = fuzzy_score(tok, title)
        if result:
            idxs.update(result[1])
    return idxs


# --------------------------------------------------------------------------- #
# Non-interactive output
# --------------------------------------------------------------------------- #
def print_list(metas):
    for m in metas:
        print(
            f"{rel_time(m['lastTs']):>4}  "
            f"{pad(project_label(m['cwd']), 28)}  "
            f"{pad(m['title'], 60)}  "
            f"{m['sessionId']}"
        )


# --------------------------------------------------------------------------- #
# Interactive picker (ANSI, single-key, no third-party deps)
# --------------------------------------------------------------------------- #
CSI = "\x1b["
RESET = CSI + "0m"
DIM = CSI + "2m"
BOLD = CSI + "1m"
INV = CSI + "7m"
CYAN = CSI + "36m"


def enable_vt_windows():
    if os.name != "nt":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VT_PROCESSING
    except Exception:
        pass


# Key names returned by read_key()
K_UP, K_DOWN, K_PGUP, K_PGDN, K_HOME, K_END = (
    "UP",
    "DOWN",
    "PGUP",
    "PGDN",
    "HOME",
    "END",
)
K_ENTER, K_ESC, K_BS, K_TAB, K_CTRLC = "ENTER", "ESC", "BS", "TAB", "CTRLC"
K_DEL = "DEL"


if os.name == "nt":
    import msvcrt

    _WIN_SPECIAL = {
        "H": K_UP,
        "P": K_DOWN,
        "K": None,
        "M": None,
        "I": K_PGUP,
        "Q": K_PGDN,
        "G": K_HOME,
        "O": K_END,
        "S": K_DEL,  # delete key -> delete the highlighted session
    }

    def read_key():
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return _WIN_SPECIAL.get(ch2, None)
        if ch in ("\r", "\n"):
            return K_ENTER
        if ch == "\x1b":
            return K_ESC
        if ch == "\x08":
            return K_BS
        if ch == "\t":
            return K_TAB
        if ch == "\x03":
            return K_CTRLC
        if not ch.isprintable():  # drop C0/C1 controls, DEL, lone surrogates
            return None
        return ch

else:
    import select as _select
    import termios
    import tty

    _POSIX_SEQ = {
        "[A": K_UP,
        "[B": K_DOWN,
        "[3~": K_DEL,
        "[5~": K_PGUP,
        "[6~": K_PGDN,
        "[H": K_HOME,
        "[F": K_END,
        "OH": K_HOME,
        "OF": K_END,
    }

    _decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def read_key():
        # Read the raw fd directly. Going through the buffered sys.stdin would
        # let read-ahead pull a whole escape sequence into Python's buffer,
        # leaving select() to see an empty kernel fd and mis-report a bare ESC.
        fd = sys.stdin.fileno()
        b = os.read(fd, 1)
        if not b:
            return None
        byte = b[0]
        if byte == 0x03:
            return K_CTRLC
        if byte in (0x0D, 0x0A):
            return K_ENTER
        if byte in (0x7F, 0x08):
            return K_BS
        if byte == 0x09:
            return K_TAB
        if byte == 0x1B:
            seq = ""
            while len(seq) < 6:
                r, _, _ = _select.select([fd], [], [], 0.05)
                if not r:
                    break
                nb = os.read(fd, 1)
                if not nb:
                    break
                seq += nb.decode("latin-1")
            if seq == "":
                return K_ESC
            return _POSIX_SEQ.get(seq, None)
        # Printable byte, possibly the first of a multibyte UTF-8 sequence.
        ch = _decoder.decode(b)
        while ch == "":
            nb = os.read(fd, 1)
            if not nb:
                break
            ch = _decoder.decode(nb)
        if not ch or not ch.isprintable():
            return None
        return ch


class _RawInput:
    """Context manager: cbreak on POSIX (no-op on Windows/msvcrt)."""

    def __enter__(self):
        if os.name != "nt":
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *a):
        if os.name != "nt":
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def _write(s):
    sys.stdout.write(s)


def render(metas, cursor, top, query, sort_mode, rows, cols):
    out = [CSI + "H"]  # cursor home
    total = len(metas)
    suffix = (
        f"  {total} match{'' if total == 1 else 'es'}  {DIM}[sort:{sort_mode}]{RESET}"
    )
    # Keep the header within the terminal width by clipping the (variable) query.
    fixed = len("ccpick  ") + 1 + len(f"  {total} matches  [sort:{sort_mode}]")
    q = clip(query, max(0, cols - fixed))
    header = f"{BOLD}ccpick{RESET}  {CYAN}{q}{RESET}{DIM}▏{RESET}{suffix}"
    out.append(CSI + "2K" + header + "\r\n")

    time_w = 4
    proj_w = min(30, max(14, cols // 4))
    rest = max(0, cols - time_w - proj_w - 4)

    for r in range(rows):
        idx = top + r
        out.append(CSI + "2K")
        if idx >= total:
            out.append("\r\n")
            continue
        m = metas[idx]
        if idx == cursor:
            line = (
                f"{rel_time(m['lastTs']):>{time_w}}  "
                f"{pad(project_label(m['cwd']), proj_w)}  "
                f"{clip(m['title'], rest)}"
            )
            out.append(INV + pad(line, cols) + RESET)
        else:
            title_frag = colorize_title(
                m['title'], rest, title_highlights(query, m['title'])
            )
            out.append(
                f"{rel_time(m['lastTs']):>{time_w}}  "
                f"{pad(project_label(m['cwd']), proj_w)}  "
                f"{title_frag}"
            )
        out.append("\r\n")

    # Footer: detail of the highlighted row + preview.
    out.append(CSI + "2K")
    if total and 0 <= cursor < total:
        m = metas[cursor]
        detail = m["cwd"] or "?"
        if m["gitBranch"] and m["gitBranch"] != "HEAD":
            detail += f"  ({m['gitBranch']})"
        out.append(DIM + clip("→ " + detail, cols) + RESET + "\r\n")
        out.append(CSI + "2K")
        preview = m["firstPrompt"] or m["summary"] or ""
        out.append(DIM + clip("  " + preview, cols) + RESET)
    else:
        out.append(DIM + "no matching sessions" + RESET + "\r\n" + CSI + "2K")
    out.append(RESET)
    out.append(CSI + "0J")  # clear anything below
    _write("".join(out))
    sys.stdout.flush()


def confirm_prompt(message, cols):
    """Show an inline y/N confirmation in the footer area and block for a
    single keypress. Returns True only for an explicit y/Y; everything
    else (including Esc, Ctrl-C, or a dropped keypress) cancels."""
    _write(CSI + "2K" + BOLD + clip(message, cols) + RESET)
    sys.stdout.flush()
    key = read_key()
    return key in ("y", "Y")


def interactive_select(metas, initial_query="", sort_mode="recent", trash_mode=False):
    """Return the chosen meta dict, or None if cancelled."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive picker needs a TTY (use --list / --json)")
    enable_vt_windows()

    all_metas = metas
    query = initial_query
    sort_idx = SORT_MODES.index(sort_mode) if sort_mode in SORT_MODES else 0
    view = apply_filter(sort_metas(all_metas, SORT_MODES[sort_idx]), query)
    cursor = 0
    top = 0

    _write(CSI + "?1049h")  # alternate screen buffer
    _write(CSI + "?25l")  # hide cursor
    try:
        with _RawInput():
            while True:
                cols, lines = shutil.get_terminal_size((100, 30))
                rows = max(3, lines - 4)  # header(1) + 2 footer + margin
                if cursor < 0:
                    cursor = 0
                if cursor >= len(view):
                    cursor = max(0, len(view) - 1)
                if cursor < top:
                    top = cursor
                elif cursor >= top + rows:
                    top = cursor - rows + 1
                # Slide the viewport up when the terminal grows so it stays full.
                top = min(max(0, top), max(0, len(view) - rows))

                render(view, cursor, top, query, SORT_MODES[sort_idx], rows, cols)

                key = read_key()
                if key in (K_ESC, K_CTRLC):
                    return None
                if key == K_ENTER:
                    if view:
                        return view[cursor]
                    continue
                if key == K_UP:
                    cursor -= 1
                elif key == K_DOWN:
                    cursor += 1
                elif key == K_PGUP:
                    cursor -= rows
                elif key == K_PGDN:
                    cursor += rows
                elif key == K_HOME:
                    cursor = 0
                elif key == K_END:
                    cursor = len(view) - 1
                elif key == K_TAB:
                    sort_idx = (sort_idx + 1) % len(SORT_MODES)
                    keep = view[cursor] if view else None
                    view = apply_filter(sort_metas(all_metas, SORT_MODES[sort_idx]), query)
                    cursor = view.index(keep) if keep in view else 0
                    top = 0
                elif key == K_DEL:
                    if view:
                        target = view[cursor]
                        verb = "Permanently delete" if trash_mode else "Delete"
                        if confirm_prompt(f'{verb} "{target["title"]}"? y/N', cols):
                            try:
                                if trash_mode:
                                    os.remove(target["path"])
                                else:
                                    move_to_trash(target["path"])
                            except OSError as e:
                                sys.stderr.write(f"warning: could not delete session: {e}\n")
                            else:
                                all_metas.remove(target)
                                view = apply_filter(
                                    sort_metas(all_metas, SORT_MODES[sort_idx]), query
                                )
                                if cursor >= len(view):
                                    cursor = max(0, len(view) - 1)
                elif key == K_BS:
                    if query:
                        query = query[:-1]
                        view = apply_filter(sort_metas(all_metas, SORT_MODES[sort_idx]), query)
                        cursor = 0
                        top = 0
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    query += key
                    view = apply_filter(sort_metas(all_metas, SORT_MODES[sort_idx]), query)
                    cursor = 0
                    top = 0
    finally:
        _write(CSI + "?25h")  # show cursor
        _write(CSI + "?1049l")  # leave alternate screen
        sys.stdout.flush()


# --------------------------------------------------------------------------- #
# Launch
# --------------------------------------------------------------------------- #
def resume(meta, no_launch=False):
    cwd = meta["cwd"]
    sid = meta["sessionId"]
    exe = shutil.which("claude") or "claude"
    missing = not cwd or not os.path.isdir(cwd)

    if no_launch:
        # Emit copy-pasteable commands (PowerShell-friendly on Windows).
        print(f'cd "{cwd}"')
        print(f"claude --resume {sid}")
        if missing:
            sys.stderr.write(f"warning: recorded directory does not exist: {cwd}\n")
            return 1
        return 0

    if missing:
        sys.stderr.write(
            f"warning: recorded directory does not exist:\n  {cwd}\n"
            f"resume manually with:  claude --resume {sid}\n"
        )
        return 1

    sys.stderr.write(f"resuming {sid}\n  in {cwd}\n")
    try:
        return subprocess.run([exe, "--resume", sid], cwd=cwd).returncode
    except FileNotFoundError:
        sys.stderr.write(
            "error: could not find the 'claude' executable on PATH.\n"
            f'cd "{cwd}" && claude --resume {sid}\n'
        )
        return 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(
        prog="ccpick",
        description="Interactively pick and resume a Claude Code session from any project.",
    )
    p.add_argument("query", nargs="*", help="initial filter query")
    p.add_argument("-l", "--list", action="store_true", help="print matches and exit (no picker)")
    p.add_argument("--json", action="store_true", help="dump session metadata as JSON and exit")
    p.add_argument("-p", "--project", metavar="SUBSTR", help="only sessions whose directory contains SUBSTR")
    p.add_argument("-s", "--sort", choices=SORT_MODES, default="recent", help="sort order (default: recent)")
    p.add_argument("-n", "--limit", type=int, default=0, help="show at most N sessions (0 = all)")
    p.add_argument("--refresh", action="store_true", help="ignore the metadata cache and rescan")
    p.add_argument("--no-launch", action="store_true", help="print the cd + resume command instead of launching")
    return p


def main(argv=None):
    reconfigure_streams()
    args = build_parser().parse_args(argv)

    metas = scan(refresh=args.refresh)
    if not metas:
        sys.stderr.write(f"no sessions found under {PROJECTS_DIR}\n")
        return 1

    if args.project:
        needle = args.project.lower()
        metas = [m for m in metas if m["cwd"] and needle in m["cwd"].lower()]

    metas = sort_metas(metas, args.sort)
    query = " ".join(args.query)

    # Non-interactive output: filter by query first, then apply the limit.
    if args.json or args.list:
        if query:
            metas = apply_filter(metas, query)
        if args.limit and args.limit > 0:
            metas = metas[: args.limit]
        if args.json:
            print(json.dumps(metas, indent=2))
        else:
            print_list(metas)
        return 0

    # Interactive: filtering happens live inside the picker, so pass the full
    # candidate pool (never pre-truncated by --limit, which would hide matches).
    if not metas:
        sys.stderr.write("no sessions match the filter\n")
        return 1

    try:
        chosen = interactive_select(metas, initial_query=query, sort_mode=args.sort)
    except RuntimeError as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    if chosen is None:
        sys.stderr.write("cancelled\n")
        return 130
    return resume(chosen, no_launch=args.no_launch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
