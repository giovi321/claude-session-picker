# ccpick delete + fuzzy search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add soft-delete (with trash/restore/auto-purge) and true fuzzy subsequence search with highlighting to `ccpick.py`.

**Architecture:** All changes live in the existing single-file `ccpick.py`, following its established pattern (no new modules). A new `test_ccpick.py` adds stdlib `unittest` coverage for every pure, TTY-independent function introduced (the scorer, the path/trash helpers). The TUI wiring itself (keybindings, `render()`, `interactive_select()`) has no automated test, same as the rest of the existing picker — verified manually per task.

**Tech Stack:** Python 3 standard library only (`os`, `shutil`, `glob`, `time`, `re`-free custom DP), `unittest` for tests.

## Global Constraints

- Zero third-party dependencies — Python 3 standard library only, for both `ccpick.py` and `test_ccpick.py`.
- Must work on both Windows (msvcrt key handling) and POSIX (raw termios key handling).
- No persisted config file — trash retention is a CLI flag (`--purge-after`, default 30 days), not saved between runs.
- Follow the existing file's conventions: section-comment headers (`# --- # Name # --- #`), docstrings only where non-obvious, existing `CSI`/`BOLD`/`CYAN`/etc. ANSI constants reused rather than redefined.

---

### Task 1: Fuzzy subsequence scorer (`fuzzy_score`)

**Files:**
- Modify: `ccpick.py` — insert a new section immediately above `def haystack(m):` (currently the first function under the `# Filtering + formatting` header).
- Create: `test_ccpick.py`

**Interfaces:**
- Produces: `fuzzy_score(token: str, haystack: str) -> tuple[float, list[int]] | None` — lower score is a better match; `matched_indices` are ascending positions in `haystack`, one per character of `token`. Case-insensitive. Returns `None` when `token`'s characters don't all appear, in order, in `haystack`.

- [ ] **Step 1: Write the failing tests**

Create `test_ccpick.py`:

```python
"""Unit tests for ccpick's pure, TTY-independent functions."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ccpick


class FuzzyScoreTests(unittest.TestCase):
    def test_exact_prefix_match(self):
        score, indices = ccpick.fuzzy_score("abc", "abc")
        self.assertEqual(indices, [0, 1, 2])

    def test_scattered_subsequence_match(self):
        score, indices = ccpick.fuzzy_score("cspkr", "claude-session-picker")
        self.assertEqual(indices, [0, 7, 15, 18, 20])

    def test_missing_character_returns_none(self):
        self.assertIsNone(ccpick.fuzzy_score("xyz", "claude-session-picker"))

    def test_out_of_order_returns_none(self):
        self.assertIsNone(ccpick.fuzzy_score("ba", "ab"))

    def test_case_insensitive(self):
        score, indices = ccpick.fuzzy_score("ABC", "xabcx")
        self.assertEqual(indices, [1, 2, 3])

    def test_contiguous_run_scores_better_than_scattered(self):
        contiguous = ccpick.fuzzy_score("ab", "xxabxx")
        scattered = ccpick.fuzzy_score("ab", "xaxbxx")
        self.assertLess(contiguous[0], scattered[0])

    def test_word_boundary_scores_better_than_mid_word(self):
        boundary = ccpick.fuzzy_score("s", "session")
        mid_word = ccpick.fuzzy_score("s", "xsession")
        self.assertLess(boundary[0], mid_word[0])

    def test_empty_token_matches_trivially(self):
        self.assertEqual(ccpick.fuzzy_score("", "anything"), (0, []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick -v`
Expected: `FAIL` / `AttributeError: module 'ccpick' has no attribute 'fuzzy_score'` for every `FuzzyScoreTests` case.

- [ ] **Step 3: Implement `fuzzy_score`**

In `ccpick.py`, insert this new section immediately above `def haystack(m):`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick -v`
Expected: all `FuzzyScoreTests` cases `PASS`.

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add fuzzy subsequence scorer for ccpick search"
```

---

### Task 2: Wire the scorer into filtering (`match`)

**Files:**
- Modify: `ccpick.py` — the existing `match(query, m)` function (currently uses `str.find` substring logic).
- Modify: `test_ccpick.py`

**Interfaces:**
- Consumes: `fuzzy_score(token, haystack) -> (score, indices) | None` (Task 1).
- Produces: `match(query, m) -> float | None` — unchanged public signature/contract (per-token AND, empty query matches everything, lower score sorts first); only the matching semantics per token become fuzzy instead of substring.

- [ ] **Step 1: Write the failing tests**

Append to `test_ccpick.py`:

```python
class MatchFilterTests(unittest.TestCase):
    def _meta(self, title="", cwd="", branch="", prompt=""):
        return {"title": title, "cwd": cwd, "gitBranch": branch, "firstPrompt": prompt}

    def test_empty_query_matches_everything(self):
        self.assertEqual(ccpick.match("", self._meta(title="anything")), 0)

    def test_single_token_fuzzy_match(self):
        m = self._meta(title="claude-session-picker")
        self.assertIsNotNone(ccpick.match("cspkr", m))

    def test_no_match_returns_none(self):
        m = self._meta(title="claude-session-picker")
        self.assertIsNone(ccpick.match("xyz", m))

    def test_multi_token_and_semantics(self):
        m = self._meta(title="ccpick", cwd=r"C:\git\obsidian-wiki", branch="n8n-fix")
        self.assertIsNotNone(ccpick.match("obsidian n8n", m))

    def test_multi_token_all_must_match(self):
        m = self._meta(title="ccpick", cwd=r"C:\git\obsidian-wiki")
        self.assertIsNone(ccpick.match("obsidian n8n", m))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.MatchFilterTests -v`
Expected: `FAIL` on `test_single_token_fuzzy_match` (the old substring `match()` returns `None` for a non-contiguous fuzzy token like `"cspkr"`); other cases may already pass incidentally.

- [ ] **Step 3: Replace `match()`**

In `ccpick.py`, replace the existing `match(query, m)` function body with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Use fuzzy scorer for ccpick session filtering"
```

---

### Task 3: Title highlighting helpers

**Files:**
- Modify: `ccpick.py` — add `clip_prefix` right after the existing `clip()` function; add `colorize_title` and `title_highlights` right before the `# Interactive picker` section header (i.e. right after `pad()`).
- Modify: `test_ccpick.py`

**Interfaces:**
- Consumes: `fuzzy_score` (Task 1), existing `clip`, `char_width`, `display_width`, `BOLD`/`CYAN`/`RESET` constants.
- Produces:
  - `clip_prefix(s: str, n: int) -> tuple[list[str], bool]` — the original characters that fit in `n` display cells, and whether truncation occurred.
  - `colorize_title(title: str, rest_width: int, highlight_idxs: set[int]) -> str` — the row's title fragment, matched characters wrapped in `BOLD + CYAN`.
  - `title_highlights(query: str, title: str) -> set[int]` — union of matched indices (in `title`) across every whitespace-separated query token.

- [ ] **Step 1: Write the failing tests**

Append to `test_ccpick.py`:

```python
class HighlightTests(unittest.TestCase):
    def test_clip_prefix_no_truncation(self):
        chars, truncated = ccpick.clip_prefix("abc", 10)
        self.assertEqual(chars, ["a", "b", "c"])
        self.assertFalse(truncated)

    def test_clip_prefix_truncates(self):
        chars, truncated = ccpick.clip_prefix("abcdef", 4)
        self.assertEqual("".join(chars), "abc")
        self.assertTrue(truncated)

    def test_colorize_title_no_highlights(self):
        self.assertEqual(ccpick.colorize_title("abc", 10, set()), "abc")

    def test_colorize_title_highlights_chars(self):
        result = ccpick.colorize_title("abc", 10, {0, 2})
        expected = (
            ccpick.BOLD + ccpick.CYAN + "a" + ccpick.RESET
            + "b"
            + ccpick.BOLD + ccpick.CYAN + "c" + ccpick.RESET
        )
        self.assertEqual(result, expected)

    def test_title_highlights_returns_matched_indices(self):
        idxs = ccpick.title_highlights("cspkr", "claude-session-picker")
        self.assertEqual(idxs, {0, 7, 15, 18, 20})

    def test_title_highlights_empty_query(self):
        self.assertEqual(ccpick.title_highlights("", "anything"), set())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.HighlightTests -v`
Expected: `FAIL` with `AttributeError: module 'ccpick' has no attribute 'clip_prefix'` (and similarly for the other two functions).

- [ ] **Step 3: Implement the helpers**

In `ccpick.py`, immediately after the existing `clip()` function, add:

```python
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
```

Then, immediately after the existing `pad()` function (right before the `# Non-interactive output` section header), add:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add title highlighting helpers for ccpick fuzzy matches"
```

---

### Task 4: Render matched-character highlighting

**Files:**
- Modify: `ccpick.py` — the per-row loop inside `render()`.

**Interfaces:**
- Consumes: `colorize_title`, `title_highlights` (Task 3).
- Produces: no new public function; `render()`'s external contract (arguments, side effect of writing to stdout) is unchanged.

**Design note:** highlighting is only drawn on non-cursor rows. The cursor row is already visually distinguished by inverse video (`INV`), and layering `BOLD+CYAN...RESET` inside an `INV`-wrapped string would have `RESET` clear the surrounding inverse-video partway through the line — avoided entirely by leaving the selected row's rendering untouched.

- [ ] **Step 1: Replace the per-row loop body**

In `ccpick.py`, inside `render()`, replace:

```python
        m = metas[idx]
        line = (
            f"{rel_time(m['lastTs']):>{time_w}}  "
            f"{pad(project_label(m['cwd']), proj_w)}  "
            f"{clip(m['title'], rest)}"
        )
        if idx == cursor:
            out.append(INV + pad(line, cols) + RESET)
        else:
            out.append(clip(line, cols))
```

with:

```python
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
```

Note this drops the final `clip(line, cols)` wrap for non-cursor rows: `time_w + 2 + proj_w + 2 + rest` already equals `cols` by construction (that's how `rest` is computed earlier in `render()`), so the row's plain-text width is already exactly bounded — the extra clip was a no-op safety net for the plain-text case, and keeping it here would miscount the embedded ANSI bytes as visible characters.

- [ ] **Step 2: Manual verification**

Run: `python ccpick.py`
- Type a scattered query (e.g. `cspkr` if you have a ccpick-related session, or any fuzzy fragment of a real session title). Confirm matched characters render bold/cyan on non-highlighted rows.
- Move the cursor onto a matching row. Confirm it still renders as plain inverse-video with no color artifacts or broken escape sequences.
- Resize the terminal narrower and confirm long titles still truncate with `…` correctly.
- If you have a session with CJK/wide characters in its title, confirm alignment is unaffected.

- [ ] **Step 3: Commit**

```bash
git add ccpick.py
git commit -m "Render fuzzy-matched characters highlighted in ccpick picker"
```

---

### Task 5: Trash path mapping + move/restore

**Files:**
- Modify: `ccpick.py` — imports, constants, new "Trash" section.
- Modify: `test_ccpick.py`

**Interfaces:**
- Produces:
  - `TRASH_DIR: str` — `~/.claude/ccpick-trash`.
  - `trash_path_for(session_path: str) -> str`
  - `live_path_for(trash_session_path: str) -> str`
  - `move_to_trash(session_path: str) -> str` — returns the trash path.
  - `restore_from_trash(trash_session_path: str) -> str` — returns the live path.

- [ ] **Step 1: Write the failing tests**

Append to `test_ccpick.py` (add `import tempfile` and `import time` to the top imports alongside the existing ones):

```python
class TrashPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_projects = ccpick.PROJECTS_DIR
        self.orig_trash = ccpick.TRASH_DIR
        ccpick.PROJECTS_DIR = os.path.join(self.tmp.name, "projects")
        ccpick.TRASH_DIR = os.path.join(self.tmp.name, "trash")
        self.addCleanup(self._restore_globals)

    def _restore_globals(self):
        ccpick.PROJECTS_DIR = self.orig_projects
        ccpick.TRASH_DIR = self.orig_trash

    def test_trash_path_for_mirrors_structure(self):
        live = os.path.join(ccpick.PROJECTS_DIR, "encoded-proj", "sess1.jsonl")
        expected = os.path.join(ccpick.TRASH_DIR, "encoded-proj", "sess1.jsonl")
        self.assertEqual(ccpick.trash_path_for(live), expected)

    def test_round_trip(self):
        live = os.path.join(ccpick.PROJECTS_DIR, "encoded-proj", "sess1.jsonl")
        trashed = ccpick.trash_path_for(live)
        self.assertEqual(ccpick.live_path_for(trashed), live)

    def test_move_to_trash_and_restore(self):
        live_dir = os.path.join(ccpick.PROJECTS_DIR, "encoded-proj")
        os.makedirs(live_dir)
        live_path = os.path.join(live_dir, "sess1.jsonl")
        with open(live_path, "w", encoding="utf-8") as fh:
            fh.write('{"type": "user"}\n')

        trash_path = ccpick.move_to_trash(live_path)

        self.assertFalse(os.path.exists(live_path))
        self.assertTrue(os.path.exists(trash_path))

        restored_path = ccpick.restore_from_trash(trash_path)

        self.assertFalse(os.path.exists(trash_path))
        self.assertTrue(os.path.exists(restored_path))
        self.assertEqual(restored_path, live_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.TrashPathTests -v`
Expected: `FAIL` with `AttributeError: module 'ccpick' has no attribute 'TRASH_DIR'`.

- [ ] **Step 3: Implement**

In `ccpick.py`, add `import time` to the imports block, alphabetically between `import sys` and `import unicodedata`.

Add `TRASH_DIR` right after `PROJECTS_DIR`:

```python
HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
TRASH_DIR = os.path.join(HOME, ".claude", "ccpick-trash")
CACHE_PATH = os.path.join(HOME, ".claude", "ccpick-cache.json")
```

Add a new section right after the `# Scan + cache` section (after `sort_metas`, before `# Filtering + formatting`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add ccpick trash move/restore primitives"
```

---

### Task 6: Auto-purge sweep

**Files:**
- Modify: `ccpick.py` — add `purge_expired_trash` to the "Trash" section (after `restore_from_trash`).
- Modify: `test_ccpick.py`

**Interfaces:**
- Consumes: `TRASH_DIR` (Task 5).
- Produces: `purge_expired_trash(retention_days: int) -> int` — permanently deletes trashed files older than `retention_days`, returns the count purged.

- [ ] **Step 1: Write the failing tests**

Append to `test_ccpick.py`:

```python
class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_trash = ccpick.TRASH_DIR
        ccpick.TRASH_DIR = os.path.join(self.tmp.name, "trash")
        self.addCleanup(self._restore_globals)

    def _restore_globals(self):
        ccpick.TRASH_DIR = self.orig_trash

    def _make_trashed(self, name, age_days):
        d = os.path.join(ccpick.TRASH_DIR, "proj")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_purge_removes_only_expired(self):
        old_path = self._make_trashed("old.jsonl", age_days=40)
        new_path = self._make_trashed("new.jsonl", age_days=5)

        purged = ccpick.purge_expired_trash(retention_days=30)

        self.assertEqual(purged, 1)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))

    def test_purge_empty_trash_dir(self):
        self.assertEqual(ccpick.purge_expired_trash(retention_days=30), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.PurgeTests -v`
Expected: `FAIL` with `AttributeError: module 'ccpick' has no attribute 'purge_expired_trash'`.

- [ ] **Step 3: Implement**

In `ccpick.py`, immediately after `restore_from_trash`, add:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add ccpick trash auto-purge sweep"
```

---

### Task 7: Delete keybinding + confirm prompt

**Files:**
- Modify: `ccpick.py` — key constants, `_WIN_SPECIAL`, `_POSIX_SEQ`, new `confirm_prompt`, `interactive_select`.

**Interfaces:**
- Consumes: `move_to_trash` (Task 5).
- Produces:
  - `K_DEL: str` — new key constant.
  - `confirm_prompt(message: str, cols: int) -> bool`
  - `interactive_select(metas, initial_query="", sort_mode="recent", trash_mode=False)` — new `trash_mode` parameter; return contract unchanged (chosen meta or `None`).

- [ ] **Step 1: Add the `K_DEL` constant**

In `ccpick.py`, change:

```python
K_ENTER, K_ESC, K_BS, K_TAB, K_CTRLC = "ENTER", "ESC", "BS", "TAB", "CTRLC"
```

to:

```python
K_ENTER, K_ESC, K_BS, K_TAB, K_CTRLC = "ENTER", "ESC", "BS", "TAB", "CTRLC"
K_DEL = "DEL"
```

- [ ] **Step 2: Repurpose the Windows Delete key**

In `_WIN_SPECIAL`, change:

```python
    _WIN_SPECIAL = {
        "H": K_UP,
        "P": K_DOWN,
        "K": None,
        "M": None,
        "I": K_PGUP,
        "Q": K_PGDN,
        "G": K_HOME,
        "O": K_END,
        "S": K_BS,  # delete key -> treat as backspace
    }
```

to:

```python
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
```

- [ ] **Step 3: Add the POSIX Delete key sequence**

In `_POSIX_SEQ`, change:

```python
    _POSIX_SEQ = {
        "[A": K_UP,
        "[B": K_DOWN,
        "[5~": K_PGUP,
        "[6~": K_PGDN,
        "[H": K_HOME,
        "[F": K_END,
        "OH": K_HOME,
        "OF": K_END,
    }
```

to:

```python
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
```

- [ ] **Step 4: Add `confirm_prompt`**

In `ccpick.py`, immediately before `def interactive_select(...)`, add:

```python
def confirm_prompt(message, cols):
    """Show an inline y/N confirmation in the footer area and block for a
    single keypress. Returns True only for an explicit y/Y; everything
    else (including Esc, Ctrl-C, or a dropped keypress) cancels."""
    _write(CSI + "2K" + BOLD + clip(message, cols) + RESET)
    sys.stdout.flush()
    key = read_key()
    return key in ("y", "Y")
```

- [ ] **Step 5: Add `trash_mode` and the `K_DEL` handler**

Change the `interactive_select` signature from:

```python
def interactive_select(metas, initial_query="", sort_mode="recent"):
```

to:

```python
def interactive_select(metas, initial_query="", sort_mode="recent", trash_mode=False):
```

Then, in the key-handling `elif` chain (after the `K_TAB` branch, before `K_BS`), add:

```python
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
```

- [ ] **Step 6: Manual verification**

Run: `python ccpick.py`
- Press `Delete` on a highlighted session. Confirm the footer shows `Delete "<title>"? y/N`.
- Press `n` (or any key other than `y`/`Y`): confirm the picker returns to normal with the session still present.
- Press `Delete` again, then `y`: confirm the row disappears from the list immediately.
- Check `~/.claude/ccpick-trash/` (or `%USERPROFILE%\.claude\ccpick-trash` on Windows): confirm the `.jsonl` moved there under the same encoded-project-dir subfolder.
- Confirm `Backspace` still edits the filter text as before (regression check for the Windows Delete-key remap).

- [ ] **Step 7: Commit**

```bash
git add ccpick.py
git commit -m "Add delete-to-trash keybinding to ccpick picker"
```

---

### Task 8: `--trash` browsing, restore, CLI flags, README

**Files:**
- Modify: `ccpick.py` — add `trash_session_files`/`scan_trash` (Trash section), `restore()` (after `resume()`), `build_parser()`, `main()`.
- Modify: `README.md` — Features, Keys table, Options table, Notes.
- Modify: `test_ccpick.py`

**Interfaces:**
- Consumes: `purge_expired_trash`, `restore_from_trash` (earlier tasks), `parse_session` (existing).
- Produces:
  - `trash_session_files() -> list[str]`
  - `scan_trash() -> list[dict]`
  - `restore(meta: dict) -> int` — exit code, mirrors `resume()`'s contract minus `no_launch`.

- [ ] **Step 1: Write the failing test**

Append to `test_ccpick.py`:

```python
class TrashScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_trash = ccpick.TRASH_DIR
        ccpick.TRASH_DIR = os.path.join(self.tmp.name, "trash")
        self.addCleanup(self._restore_globals)

    def _restore_globals(self):
        ccpick.TRASH_DIR = self.orig_trash

    def test_trash_session_files_empty_when_no_dir(self):
        self.assertEqual(ccpick.trash_session_files(), [])

    def test_trash_session_files_finds_nested_jsonl(self):
        d = os.path.join(ccpick.TRASH_DIR, "proj")
        os.makedirs(d)
        path = os.path.join(d, "sess1.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"type": "user"}\n')
        self.assertEqual(ccpick.trash_session_files(), [path])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_ccpick.TrashScanTests -v`
Expected: `FAIL` with `AttributeError: module 'ccpick' has no attribute 'trash_session_files'`.

- [ ] **Step 3: Implement `trash_session_files` / `scan_trash`**

In `ccpick.py`, immediately after `purge_expired_trash` (end of the "Trash" section), add:

```python
def trash_session_files():
    if not os.path.isdir(TRASH_DIR):
        return []
    return glob.glob(os.path.join(TRASH_DIR, "*", "*.jsonl"))


def scan_trash():
    """Parse every trashed session (no cache -- trash is typically small
    and this only runs for --trash)."""
    metas = []
    for path in trash_session_files():
        try:
            metas.append(parse_session(path))
        except Exception:
            continue
    return metas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_ccpick -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Add `restore()`**

In `ccpick.py`, immediately after the existing `resume()` function, add:

```python
def restore(meta):
    try:
        dst = restore_from_trash(meta["path"])
    except OSError as e:
        sys.stderr.write(f"error: could not restore session: {e}\n")
        return 1
    sys.stderr.write(f"restored {meta['sessionId']}\n  to {dst}\n")
    return 0
```

- [ ] **Step 6: Add CLI flags**

In `build_parser()`, change:

```python
    p.add_argument("--refresh", action="store_true", help="ignore the metadata cache and rescan")
    p.add_argument("--no-launch", action="store_true", help="print the cd + resume command instead of launching")
    return p
```

to:

```python
    p.add_argument("--refresh", action="store_true", help="ignore the metadata cache and rescan")
    p.add_argument("--no-launch", action="store_true", help="print the cd + resume command instead of launching")
    p.add_argument("--trash", action="store_true", help="browse trash instead of live sessions (Enter restores, Delete permanently removes)")
    p.add_argument("--purge-after", type=int, default=30, metavar="N", help="trash retention in days before auto-purge (default: 30)")
    return p
```

- [ ] **Step 7: Wire `main()`**

Replace the start of `main()`:

```python
def main(argv=None):
    reconfigure_streams()
    args = build_parser().parse_args(argv)

    metas = scan(refresh=args.refresh)
    if not metas:
        sys.stderr.write(f"no sessions found under {PROJECTS_DIR}\n")
        return 1
```

with:

```python
def main(argv=None):
    reconfigure_streams()
    args = build_parser().parse_args(argv)

    purged = purge_expired_trash(args.purge_after)
    if purged:
        sys.stderr.write(f"purged {purged} expired trash session(s)\n")

    if args.trash:
        metas = scan_trash()
        if not metas:
            sys.stderr.write(f"no trashed sessions found under {TRASH_DIR}\n")
            return 1
    else:
        metas = scan(refresh=args.refresh)
        if not metas:
            sys.stderr.write(f"no sessions found under {PROJECTS_DIR}\n")
            return 1
```

Then replace the final dispatch:

```python
    try:
        chosen = interactive_select(metas, initial_query=query, sort_mode=args.sort)
    except RuntimeError as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    if chosen is None:
        sys.stderr.write("cancelled\n")
        return 130
    return resume(chosen, no_launch=args.no_launch)
```

with:

```python
    try:
        chosen = interactive_select(
            metas, initial_query=query, sort_mode=args.sort, trash_mode=args.trash
        )
    except RuntimeError as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    if chosen is None:
        sys.stderr.write("cancelled\n")
        return 130
    if args.trash:
        return restore(chosen)
    return resume(chosen, no_launch=args.no_launch)
```

(The rest of `main()` — project filter, sort, `-l`/`--json` handling — is unchanged; it already operates generically on whatever `metas` list it was given.)

- [ ] **Step 8: Update README.md**

In the Features list, add:

```markdown
- Delete a session to a recoverable trash folder (`Delete` key); browse/restore trash with `--trash`; auto-purges after a configurable retention period
```

In the Keys table, add a row:

```markdown
| Delete | delete the highlighted session (moves to trash; permanently removes in `--trash` mode) |
```

In the Options table, add two rows:

```markdown
| `--trash` | browse trash instead of live sessions (`Enter` restores, `Delete` permanently removes) |
| `--purge-after N` | trash retention in days before auto-purge (default: 30) |
```

In the Notes section, add:

```markdown
- Deleted sessions move to `~/.claude/ccpick-trash/` (mirroring the live layout) rather than being removed immediately; browse and restore them with `ccpick --trash`. Expired trash (older than `--purge-after` days, default 30) is purged automatically at the start of every run.
```

- [ ] **Step 9: Manual verification**

Run: `python ccpick.py --trash`
- With at least one session deleted from Task 7's verification, confirm it shows up here.
- Press `Enter` on it: confirm it moves back under `~/.claude/projects/<encoded-dir>/` and `claude --resume` would find it again (verify by running plain `python ccpick.py` and confirming the session reappears).
- Delete another session, then run `python ccpick.py --trash`, press `Delete`, confirm `y`: confirm the file is gone from disk entirely (not re-trashed).
- Run `python ccpick.py --purge-after 0`: confirm anything currently in trash gets purged immediately and the stderr message `purged N expired trash session(s)` appears.

- [ ] **Step 10: Commit**

```bash
git add ccpick.py test_ccpick.py README.md
git commit -m "Add ccpick --trash browsing, restore, and purge CLI flags"
```
