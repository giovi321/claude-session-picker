# ccpick pin + save-for-later Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable per-session pinning (capped, floats to top) and save-for-later bookmarking (unlimited watchlist group) to the `ccpick` interactive picker.

**Architecture:** A new durable state file `~/.claude/ccpick-marks.json` holds pin/save membership keyed by `sessionId`, loaded into a pure `Marks` object. Grouping is a *rendering* transform: the picker's cursor still indexes a flat list of session metas (navigation unchanged), while a pure `build_rows` helper interleaves non-selectable header rows for display and scroll. Marks and grouping never touch the disposable mtime cache.

**Tech Stack:** Python 3 standard library only (no third-party deps). Interactive TUI via ANSI + `msvcrt` (Windows) / `termios` (POSIX). Tests via stdlib `unittest` in `test_ccpick.py`.

## Global Constraints

- Zero third-party dependencies — Python 3 standard library only.
- Python 3.8+; must work on both Windows (msvcrt) and POSIX (termios) paths.
- Durable user state (`ccpick-marks.json`) is a SEPARATE file from the mtime+size cache (`ccpick-cache.json`), which stays disposable.
- Pin and save are mutually exclusive per session. Pin cap default 3, via `--max-pins N`.
- Sessions keyed by `sessionId` (the transcript UUID), never by the lossy encoded path.
- When the user has marked nothing, every surface (picker layout, `--list`) must be byte-for-byte identical to today's output.
- Commit messages: plain, imperative, no Claude/AI attribution, no `Co-Authored-By`, no session-link trailers. No surname anywhere.
- Run tests with `python -m unittest test_ccpick -v` (single case: `python -m unittest test_ccpick.ClassName.test_name -v`).

---

### Task 1: `Marks` in-memory state

**Files:**
- Modify: `ccpick.py` (add `Marks` class near the other data helpers, after the `sort_metas` block ~line 293)
- Test: `test_ccpick.py`

**Interfaces:**
- Produces:
  - `class Marks` with attributes `pins: list[str]`, `saved: list[str]`
  - `Marks(pins=None, saved=None)` constructor (copies the lists)
  - `is_pinned(sid) -> bool`, `is_saved(sid) -> bool`
  - `toggle_pin(sid, max_pins) -> "pinned"|"unpinned"|"cap"`
  - `toggle_save(sid) -> "saved"|"unsaved"`
  - `drop(sid) -> bool` (True if it removed the sid from either list)

- [ ] **Step 1: Write the failing tests**

Add to `test_ccpick.py` (before the `if __name__` block):

```python
class MarksTests(unittest.TestCase):
    def test_pin_and_unpin(self):
        m = ccpick.Marks()
        self.assertEqual(m.toggle_pin("a", 3), "pinned")
        self.assertTrue(m.is_pinned("a"))
        self.assertEqual(m.toggle_pin("a", 3), "unpinned")
        self.assertFalse(m.is_pinned("a"))

    def test_pin_cap_refuses(self):
        m = ccpick.Marks(pins=["a", "b", "c"])
        self.assertEqual(m.toggle_pin("d", 3), "cap")
        self.assertFalse(m.is_pinned("d"))
        self.assertEqual(m.pins, ["a", "b", "c"])

    def test_pin_custom_cap(self):
        m = ccpick.Marks(pins=["a"])
        self.assertEqual(m.toggle_pin("b", 1), "cap")
        m2 = ccpick.Marks(pins=["a"])
        self.assertEqual(m2.toggle_pin("b", 5), "pinned")

    def test_pin_preserves_order(self):
        m = ccpick.Marks()
        m.toggle_pin("a", 3)
        m.toggle_pin("b", 3)
        self.assertEqual(m.pins, ["a", "b"])

    def test_pinning_saved_item_promotes_it(self):
        m = ccpick.Marks(saved=["a"])
        self.assertEqual(m.toggle_pin("a", 3), "pinned")
        self.assertTrue(m.is_pinned("a"))
        self.assertFalse(m.is_saved("a"))

    def test_save_and_unsave(self):
        m = ccpick.Marks()
        self.assertEqual(m.toggle_save("a"), "saved")
        self.assertTrue(m.is_saved("a"))
        self.assertEqual(m.toggle_save("a"), "unsaved")
        self.assertFalse(m.is_saved("a"))

    def test_saving_pinned_item_moves_it(self):
        m = ccpick.Marks(pins=["a"])
        self.assertEqual(m.toggle_save("a"), "saved")
        self.assertTrue(m.is_saved("a"))
        self.assertFalse(m.is_pinned("a"))

    def test_drop_removes_from_both(self):
        m = ccpick.Marks(pins=["a"], saved=["b"])
        self.assertTrue(m.drop("a"))
        self.assertTrue(m.drop("b"))
        self.assertFalse(m.drop("c"))
        self.assertEqual(m.pins, [])
        self.assertEqual(m.saved, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.MarksTests -v`
Expected: FAIL with `AttributeError: module 'ccpick' has no attribute 'Marks'`

- [ ] **Step 3: Implement `Marks`**

Insert into `ccpick.py` after the `sort_metas` function (before the Trash section header comment):

```python
# --------------------------------------------------------------------------- #
# Marks (pin / save-for-later)
# --------------------------------------------------------------------------- #
class Marks:
    """Durable pin / save-for-later state, keyed by sessionId. Pin and save
    are mutually exclusive per session; pins are order-preserving (that order
    is the pinned-group display order) and capped by a caller-supplied max."""

    def __init__(self, pins=None, saved=None):
        self.pins = list(pins) if pins else []
        self.saved = list(saved) if saved else []

    def is_pinned(self, sid):
        return sid in self.pins

    def is_saved(self, sid):
        return sid in self.saved

    def toggle_pin(self, sid, max_pins):
        if sid in self.pins:
            self.pins.remove(sid)
            return "unpinned"
        if len(self.pins) >= max_pins:
            return "cap"
        if sid in self.saved:
            self.saved.remove(sid)  # promote a saved item to pinned
        self.pins.append(sid)
        return "pinned"

    def toggle_save(self, sid):
        if sid in self.saved:
            self.saved.remove(sid)
            return "unsaved"
        if sid in self.pins:
            self.pins.remove(sid)  # move a pinned item to saved
        self.saved.append(sid)
        return "saved"

    def drop(self, sid):
        """Remove sid from both lists (used when a session is trashed).
        Returns True if anything was removed."""
        changed = False
        if sid in self.pins:
            self.pins.remove(sid)
            changed = True
        if sid in self.saved:
            self.saved.remove(sid)
            changed = True
        return changed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick.MarksTests -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add Marks pin/save state with cap and mutual exclusion"
```

---

### Task 2: Marks persistence

**Files:**
- Modify: `ccpick.py` (add `MARKS_PATH`/`MARKS_VERSION` constants near `CACHE_PATH` ~line 31; add `load_marks`/`save_marks` right after the `Marks` class from Task 1)
- Test: `test_ccpick.py`

**Interfaces:**
- Consumes: `Marks` (Task 1)
- Produces:
  - `MARKS_PATH` (module global, monkeypatchable in tests like `CACHE_PATH`)
  - `MARKS_VERSION = 1`
  - `load_marks() -> Marks` (empty `Marks` on missing/corrupt/wrong-version)
  - `save_marks(marks) -> None` (atomic tmp+replace, swallows `OSError`)

- [ ] **Step 1: Write the failing tests**

Add to `test_ccpick.py`:

```python
class MarksPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig = ccpick.MARKS_PATH
        ccpick.MARKS_PATH = os.path.join(self.tmp.name, "ccpick-marks.json")
        self.addCleanup(self._restore)

    def _restore(self):
        ccpick.MARKS_PATH = self.orig

    def test_missing_file_returns_empty(self):
        m = ccpick.load_marks()
        self.assertEqual(m.pins, [])
        self.assertEqual(m.saved, [])

    def test_round_trip(self):
        ccpick.save_marks(ccpick.Marks(pins=["a", "b"], saved=["c"]))
        m = ccpick.load_marks()
        self.assertEqual(m.pins, ["a", "b"])
        self.assertEqual(m.saved, ["c"])

    def test_malformed_file_returns_empty(self):
        with open(ccpick.MARKS_PATH, "w", encoding="utf-8") as fh:
            fh.write("not json{{{")
        self.assertEqual(ccpick.load_marks().pins, [])

    def test_wrong_version_returns_empty(self):
        with open(ccpick.MARKS_PATH, "w", encoding="utf-8") as fh:
            json.dump({"v": 999, "pins": ["a"], "saved": []}, fh)
        self.assertEqual(ccpick.load_marks().pins, [])
```

Add `import json` to the test file's imports if not already present (it is not — the current file imports `os, sys, tempfile, time, unittest`). Add `import json` at the top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.MarksPersistenceTests -v`
Expected: FAIL with `AttributeError: module 'ccpick' has no attribute 'MARKS_PATH'` (or `load_marks`)

- [ ] **Step 3: Implement constants + persistence**

Add constants next to the existing cache constants in `ccpick.py` (after `CACHE_VERSION = 3`, ~line 32):

```python
MARKS_PATH = os.path.join(HOME, ".claude", "ccpick-marks.json")
MARKS_VERSION = 1
```

Add these functions immediately after the `Marks` class:

```python
def load_marks():
    """Read durable pin/save state. Missing, unreadable, malformed, or
    wrong-version content all yield an empty Marks (same defensive posture as
    load_cache -- a lost marks file must never crash the picker)."""
    try:
        with open(MARKS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("v") == MARKS_VERSION:
            pins = data.get("pins")
            saved = data.get("saved")
            return Marks(
                pins if isinstance(pins, list) else [],
                saved if isinstance(saved, list) else [],
            )
    except (OSError, ValueError):
        pass
    return Marks()


def save_marks(marks):
    try:
        tmp = MARKS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {"v": MARKS_VERSION, "pins": marks.pins, "saved": marks.saved}, fh
            )
        os.replace(tmp, MARKS_PATH)
    except OSError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_ccpick.MarksPersistenceTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add atomic load/save for the marks file"
```

---

### Task 3: Grouping + rendering-support pure helpers

**Files:**
- Modify: `ccpick.py` (add glyph constants near the ANSI constants ~line 641; add `row_marker`, `partition_marked`, `build_rows`, `session_row_indices` in the "Filtering + formatting" section, after `title_highlights` ~line 617)
- Test: `test_ccpick.py`

**Interfaces:**
- Consumes: `Marks` (Task 1); meta dicts have keys `sessionId`, `title`, `cwd`, etc. (from `parse_session`)
- Produces:
  - `PIN_GLYPH = "★"`, `SAVE_GLYPH = "◆"`
  - `row_marker(marks, sid) -> str` — a 2-cell string (`"★ "`, `"◆ "`, or `"  "`)
  - `partition_marked(sorted_metas, marks) -> (pinned, saved, others)` — three meta lists; pinned in `marks.pins` order, saved+others in incoming order; each meta in exactly one bucket; dangling pin ids (not present in `sorted_metas`) skipped
  - `build_rows(pinned, saved, others, grouped) -> list[dict]` — rows are `{"kind": "header", "label": str}` or `{"kind": "session", "meta": dict}`; when `grouped` is False returns flat session rows for `others` only; empty groups omit their header
  - `session_row_indices(rows) -> list[int]` — indices of the session rows, in order

- [ ] **Step 1: Write the failing tests**

Add to `test_ccpick.py`:

```python
class GroupingTests(unittest.TestCase):
    def _meta(self, sid, title="t"):
        return {"sessionId": sid, "title": title, "cwd": "", "gitBranch": "",
                "firstPrompt": "", "summary": None, "lastTs": ""}

    def test_row_marker_glyphs(self):
        marks = ccpick.Marks(pins=["a"], saved=["b"])
        self.assertEqual(ccpick.display_width(ccpick.row_marker(marks, "a")), 2)
        self.assertEqual(ccpick.display_width(ccpick.row_marker(marks, "b")), 2)
        self.assertEqual(ccpick.row_marker(marks, "c"), "  ")
        self.assertTrue(ccpick.row_marker(marks, "a").startswith(ccpick.PIN_GLYPH))
        self.assertTrue(ccpick.row_marker(marks, "b").startswith(ccpick.SAVE_GLYPH))

    def test_partition_orders_and_excludes(self):
        metas = [self._meta("a"), self._meta("b"), self._meta("c"), self._meta("d")]
        marks = ccpick.Marks(pins=["c", "a"], saved=["d"])
        pinned, saved, others = ccpick.partition_marked(metas, marks)
        self.assertEqual([m["sessionId"] for m in pinned], ["c", "a"])  # pin order
        self.assertEqual([m["sessionId"] for m in saved], ["d"])
        self.assertEqual([m["sessionId"] for m in others], ["b"])

    def test_partition_skips_dangling_pin(self):
        metas = [self._meta("a")]
        marks = ccpick.Marks(pins=["a", "ghost"])
        pinned, saved, others = ccpick.partition_marked(metas, marks)
        self.assertEqual([m["sessionId"] for m in pinned], ["a"])
        self.assertEqual(others, [])

    def test_build_rows_flat(self):
        metas = [self._meta("a"), self._meta("b")]
        rows = ccpick.build_rows([], [], metas, grouped=False)
        self.assertTrue(all(r["kind"] == "session" for r in rows))
        self.assertEqual(len(rows), 2)

    def test_build_rows_grouped_has_headers(self):
        rows = ccpick.build_rows(
            [self._meta("a")], [self._meta("b")], [self._meta("c")], grouped=True
        )
        kinds = [(r["kind"], r.get("label")) for r in rows]
        self.assertEqual(kinds[0], ("header", "PINNED"))
        self.assertEqual(rows[1]["meta"]["sessionId"], "a")
        self.assertEqual(kinds[2], ("header", "SAVED FOR LATER"))
        self.assertEqual(kinds[4][0], "header")  # "── sessions ──"

    def test_build_rows_omits_empty_group(self):
        rows = ccpick.build_rows(
            [self._meta("a")], [], [self._meta("c")], grouped=True
        )
        labels = [r["label"] for r in rows if r["kind"] == "header"]
        self.assertNotIn("SAVED FOR LATER", labels)
        self.assertIn("PINNED", labels)

    def test_session_row_indices_skips_headers(self):
        rows = ccpick.build_rows(
            [self._meta("a")], [self._meta("b")], [], grouped=True
        )
        sel = ccpick.session_row_indices(rows)
        self.assertEqual([rows[i]["meta"]["sessionId"] for i in sel], ["a", "b"])
        self.assertTrue(all(rows[i]["kind"] == "session" for i in sel))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.GroupingTests -v`
Expected: FAIL with `AttributeError` for `row_marker` / `PIN_GLYPH`

- [ ] **Step 3: Implement glyph constants**

Add near the ANSI constants block (after `CYAN = CSI + "36m"`, ~line 641):

```python
PIN_GLYPH = "★"
SAVE_GLYPH = "◆"
```

- [ ] **Step 4: Implement the helpers**

Add in the "Filtering + formatting" section, after `title_highlights` (~line 617). `row_marker` uses the existing `pad()` so a wide-glyph terminal still gets exactly 2 cells:

```python
def row_marker(marks, sid):
    """Two-cell leading marker for a session row: pinned, saved, or blank.
    Uses pad() so the column is exactly 2 display cells regardless of whether
    the terminal renders the glyph as 1 or 2 wide."""
    if marks.is_pinned(sid):
        ch = PIN_GLYPH
    elif marks.is_saved(sid):
        ch = SAVE_GLYPH
    else:
        ch = ""
    return pad(ch, 2)


def partition_marked(sorted_metas, marks):
    """Split an already-sorted meta list into (pinned, saved, others). Pinned
    follow marks.pins order; saved and others keep the incoming (sort-mode)
    order. Each session lands in exactly one bucket; pin ids with no matching
    session (dangling) are skipped."""
    by_id = {m["sessionId"]: m for m in sorted_metas}
    pinned_ids = set(marks.pins)
    pinned = [by_id[sid] for sid in marks.pins if sid in by_id]
    saved = [
        m for m in sorted_metas
        if m["sessionId"] not in pinned_ids and marks.is_saved(m["sessionId"])
    ]
    others = [
        m for m in sorted_metas
        if m["sessionId"] not in pinned_ids and not marks.is_saved(m["sessionId"])
    ]
    return pinned, saved, others


def build_rows(pinned, saved, others, grouped):
    """Build the picker's display-row list. Header rows are
    {'kind': 'header', 'label': ...} (non-selectable); session rows are
    {'kind': 'session', 'meta': m}. When not grouped, returns a flat list of
    session rows for `others` (pinned/saved are ignored). Empty groups omit
    both their header and their rows."""
    if not grouped:
        return [{"kind": "session", "meta": m} for m in others]
    rows = []
    for label, group in (
        ("PINNED", pinned),
        ("SAVED FOR LATER", saved),
        ("── sessions ──", others),
    ):
        if not group:
            continue
        rows.append({"kind": "header", "label": label})
        rows.extend({"kind": "session", "meta": m} for m in group)
    return rows


def session_row_indices(rows):
    """Indices of the selectable (session) rows, in order. The cursor indexes
    the session list; this maps a session position to its display-row index
    so scroll math can keep headers on-screen."""
    return [i for i, r in enumerate(rows) if r["kind"] == "session"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest test_ccpick.GroupingTests -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Add grouping and row-model helpers for pin/save display"
```

---

### Task 4: Wire pins/saves into the interactive picker

This is the integration task. It rewrites `render()` and `interactive_select()` and wires marks + `--max-pins` into `main()`. The TUI has no automated harness, so verification is a manual keyboard checklist (per the project's existing convention). No behavior change when nothing is marked.

**Files:**
- Modify: `ccpick.py` — `render()` (~line 785-842), `interactive_select()` (~line 855-946), `build_parser()` (~line 998), `main()` (~line 1016-1072)

**Interfaces:**
- Consumes: `Marks`, `load_marks`, `save_marks` (Tasks 1-2); `partition_marked`, `build_rows`, `session_row_indices`, `row_marker` (Task 3); existing `apply_filter`, `sort_metas`, `move_to_trash`, `confirm_prompt`.
- Produces: new `render()` and `interactive_select()` signatures (below), consumed only within `main()`.

- [ ] **Step 1: Replace `render()`**

Replace the entire existing `render(...)` function with this. New signature adds `sel`, `height` (renamed from `rows` for clarity vs the row-model), `marks`, `show_markers`, `action_mode`, `notice`:

```python
def render(display_rows, sel, cursor, top, query, sort_mode, height, cols,
           marks, show_markers, action_mode, notice):
    out = [CSI + "H"]  # cursor home
    total = len(sel)  # selectable sessions, not display rows
    suffix = (
        f"  {total} match{'' if total == 1 else 'es'}  {DIM}[sort:{sort_mode}]{RESET}"
    )
    fixed = len("ccpick  ") + 1 + len(f"  {total} matches  [sort:{sort_mode}]")
    q = clip(query, max(0, cols - fixed))
    header = f"{BOLD}ccpick{RESET}  {CYAN}{q}{RESET}{DIM}▏{RESET}{suffix}"
    out.append(CSI + "2K" + header + "\r\n")

    time_w = 4
    proj_w = min(30, max(14, cols // 4))
    marker_w = 2 if show_markers else 0
    rest = max(0, cols - time_w - proj_w - 4 - marker_w)

    cur_row = sel[cursor] if (sel and 0 <= cursor < len(sel)) else -1

    for r in range(height):
        idx = top + r
        out.append(CSI + "2K")
        if idx >= len(display_rows):
            out.append("\r\n")
            continue
        row = display_rows[idx]
        if row["kind"] == "header":
            out.append(DIM + pad(row["label"], cols) + RESET + "\r\n")
            continue
        m = row["meta"]
        glyph = row_marker(marks, m["sessionId"]) if show_markers else ""
        if idx == cur_row:
            line = (
                f"{glyph}"
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
                f"{glyph}"
                f"{rel_time(m['lastTs']):>{time_w}}  "
                f"{pad(project_label(m['cwd']), proj_w)}  "
                f"{title_frag}"
            )
        out.append("\r\n")

    # Footer line 1: action prompt / transient notice / detail of highlighted row.
    out.append(CSI + "2K")
    if action_mode:
        out.append(BOLD + clip("· [p]in  [b]ookmark   Esc", cols) + RESET + "\r\n")
    elif notice:
        out.append(BOLD + clip("· " + notice, cols) + RESET + "\r\n")
    elif cur_row >= 0:
        m = display_rows[cur_row]["meta"]
        detail = m["cwd"] or "?"
        if m["gitBranch"] and m["gitBranch"] != "HEAD":
            detail += f"  ({m['gitBranch']})"
        out.append(DIM + clip("→ " + detail, cols) + RESET + "\r\n")
    else:
        out.append(DIM + "no matching sessions" + RESET + "\r\n")

    # Footer line 2: preview of the highlighted row's first prompt / summary.
    out.append(CSI + "2K")
    if cur_row >= 0:
        m = display_rows[cur_row]["meta"]
        preview = m["firstPrompt"] or m["summary"] or ""
        out.append(DIM + clip("  " + preview, cols) + RESET)
    out.append(RESET)
    out.append(CSI + "0J")  # clear anything below
    _write("".join(out))
    sys.stdout.flush()
```

- [ ] **Step 2: Replace `interactive_select()`**

Replace the entire existing `interactive_select(...)` with this. It adds `marks`/`max_pins` params, a `build_view()`/`rebuild()` pair (DRY replacement for the repeated `view = apply_filter(...)` lines), header-aware scroll, the `.`→p/b action mode, and marks-drop on trash:

```python
def interactive_select(metas, initial_query="", sort_mode="recent",
                       trash_mode=False, marks=None, max_pins=3):
    """Return the chosen meta dict, or None if cancelled."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive picker needs a TTY (use --list / --json)")
    enable_vt_windows()
    if marks is None:
        marks = Marks()

    all_metas = metas
    query = initial_query
    sort_idx = SORT_MODES.index(sort_mode) if sort_mode in SORT_MODES else 0
    action_mode = False
    notice = None  # transient one-frame footer message

    def build_view():
        """Recompute (display_rows, sel, view, show_markers) from the current
        query / sort / marks. Grouping is on only for an empty query with at
        least one *resolvable* mark; any query flattens to the fuzzy rank."""
        sorted_all = sort_metas(all_metas, SORT_MODES[sort_idx])
        show = not trash_mode and bool(marks.pins or marks.saved)
        if query:
            rows = build_rows([], [], apply_filter(sorted_all, query), False)
        else:
            pinned, saved, others = partition_marked(sorted_all, marks)
            rows = build_rows(pinned, saved, others, bool(pinned or saved))
        sel = session_row_indices(rows)
        view = [rows[i]["meta"] for i in sel]
        return rows, sel, view, show

    display_rows, sel, view, show_markers = build_view()
    cursor = 0
    top = 0

    def rebuild(keep=None):
        nonlocal display_rows, sel, view, show_markers, cursor, top
        display_rows, sel, view, show_markers = build_view()
        if keep is not None and keep in view:
            cursor = view.index(keep)
        else:
            cursor = 0
        top = 0

    _write(CSI + "?1049h")  # alternate screen buffer
    _write(CSI + "?25l")  # hide cursor
    try:
        with _RawInput():
            while True:
                cols, lines = shutil.get_terminal_size((100, 30))
                height = max(3, lines - 4)  # header(1) + 2 footer + margin
                if cursor < 0:
                    cursor = 0
                if cursor >= len(view):
                    cursor = max(0, len(view) - 1)
                # Scroll in display-row space so group headers stay on-screen.
                target = sel[cursor] if (sel and cursor < len(sel)) else 0
                if target < top:
                    top = target
                elif target >= top + height:
                    top = target - height + 1
                top = min(max(0, top), max(0, len(display_rows) - height))

                render(display_rows, sel, cursor, top, query,
                       SORT_MODES[sort_idx], height, cols, marks,
                       show_markers, action_mode, notice)
                notice = None  # cleared after one rendered frame

                key = read_key()

                if action_mode:
                    action_mode = False
                    if view and key in ("p", "b"):
                        keep = view[cursor]
                        sid = keep["sessionId"]
                        if key == "p":
                            res = marks.toggle_pin(sid, max_pins)
                            notice = {
                                "pinned": "pinned",
                                "unpinned": "unpinned",
                                "cap": f"{max_pins} pins max — unpin one first",
                            }[res]
                        else:
                            res = marks.toggle_save(sid)
                            notice = {"saved": "saved", "unsaved": "unsaved"}[res]
                        if res != "cap":
                            save_marks(marks)
                            rebuild(keep=keep)
                    continue

                if key in (K_ESC, K_CTRLC):
                    return None
                if key == K_ENTER:
                    if view:
                        return view[cursor]
                    continue
                if key == "." and not trash_mode:
                    action_mode = True
                    continue
                if key == K_UP:
                    cursor -= 1
                elif key == K_DOWN:
                    cursor += 1
                elif key == K_PGUP:
                    cursor -= height
                elif key == K_PGDN:
                    cursor += height
                elif key == K_HOME:
                    cursor = 0
                elif key == K_END:
                    cursor = len(view) - 1
                elif key == K_TAB:
                    sort_idx = (sort_idx + 1) % len(SORT_MODES)
                    rebuild(keep=view[cursor] if view else None)
                elif key == K_DEL:
                    if view:
                        target_meta = view[cursor]
                        verb = "Permanently delete" if trash_mode else "Delete"
                        if confirm_prompt(f'{verb} "{target_meta["title"]}"? y/N', cols):
                            try:
                                if trash_mode:
                                    os.remove(target_meta["path"])
                                else:
                                    move_to_trash(target_meta["path"])
                            except OSError as e:
                                sys.stderr.write(f"warning: could not delete session: {e}\n")
                            else:
                                all_metas.remove(target_meta)
                                if not trash_mode and marks.drop(target_meta["sessionId"]):
                                    save_marks(marks)
                                rebuild()
                elif key == K_BS:
                    if query:
                        query = query[:-1]
                        rebuild()
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    query += key
                    rebuild()
    finally:
        _write(CSI + "?25h")  # show cursor
        _write(CSI + "?1049l")  # leave alternate screen
        sys.stdout.flush()
```

- [ ] **Step 3: Add the `--max-pins` flag**

In `build_parser()`, add after the `--purge-after` argument:

```python
    p.add_argument("--max-pins", type=int, default=3, metavar="N", help="maximum pinned sessions (default: 3)")
```

- [ ] **Step 4: Load marks and pass them through in `main()`**

In `main()`, after the line `metas = sort_metas(metas, args.sort)` and before `query = " ".join(args.query)`, add:

```python
    marks = Marks() if args.trash else load_marks()
```

Then change the interactive call from:

```python
        chosen = interactive_select(
            metas, initial_query=query, sort_mode=args.sort, trash_mode=args.trash
        )
```

to:

```python
        chosen = interactive_select(
            metas, initial_query=query, sort_mode=args.sort, trash_mode=args.trash,
            marks=marks, max_pins=args.max_pins,
        )
```

(The `--json` / `--list` branch also now has `marks` in scope; Task 5 wires it in.)

- [ ] **Step 5: Run the existing test suite (no regressions)**

Run: `python -m unittest test_ccpick -v`
Expected: PASS (all existing + Tasks 1-3 tests). The render/loop rewrite is not unit-tested but must not break the pure-function tests.

- [ ] **Step 6: Manual verification in a real terminal**

Run `python ccpick.py` and confirm each:
1. With nothing marked, the layout is unchanged (no leading marker column, no headers).
2. Highlight a row, press `.` — footer shows `· [p]in  [b]ookmark   Esc`. Press `p` — footer flashes `pinned`, row gains `★`, jumps into a `PINNED` header group at the top.
3. `.` then `b` on another row — it appears under `SAVED FOR LATER`. A `★`/`◆` column is now present on every row.
4. Pin up to the cap (default 3), then `.`+`p` a 4th — footer shows `3 pins max — unpin one first`, nothing changes.
5. `.`+`p` on a pinned row unpins it; `.`+`b` on a pinned row moves it to saved (mutual exclusion).
6. Type a query — groups collapse to one flat ranked list, glyphs still shown; clear the query — groups return.
7. `.` then `Esc` (or any other key) leaves action mode with no change.
8. Arrow up/down glides over the dim headers without landing on them; the highlighted row's header stays visible when scrolling.
9. `Delete` on a pinned row (confirm `y`) removes it and its pin; relaunch — it is gone and not pinned.
10. Relaunch `python ccpick.py` — pins/saves persist. `cat ~/.claude/ccpick-marks.json` shows `{"v": 1, "pins": [...], "saved": [...]}`.
11. `python ccpick.py --trash` — `.` does nothing (no action mode), no marker column.

If POSIX is available, repeat steps 2-8 there.

- [ ] **Step 7: Commit**

```bash
git add ccpick.py
git commit -m "Wire pin/save into the interactive picker with grouped view and action mode"
```

---

### Task 5: Markers in `--list` and `--json`

**Files:**
- Modify: `ccpick.py` — `print_list()` (~line 622) and the `--json`/`--list` branch of `main()` (~line 1043-1052)
- Test: `test_ccpick.py`

**Interfaces:**
- Consumes: `Marks`, `row_marker` (Tasks 1, 3)
- Produces: `print_list(metas, marks=None, show_markers=False)` (backward-compatible defaults)

- [ ] **Step 1: Write the failing tests**

Add to `test_ccpick.py`:

```python
import io
import contextlib


class ListMarkerTests(unittest.TestCase):
    def _meta(self, sid, title="t"):
        return {"sessionId": sid, "title": title, "cwd": "/x/y",
                "gitBranch": "", "firstPrompt": "", "summary": None, "lastTs": ""}

    def test_print_list_no_markers_by_default(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ccpick.print_list([self._meta("a")])
        self.assertFalse(buf.getvalue().startswith("★"))
        self.assertFalse(buf.getvalue().startswith("◆"))

    def test_print_list_shows_pin_glyph(self):
        marks = ccpick.Marks(pins=["a"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ccpick.print_list([self._meta("a")], marks=marks, show_markers=True)
        self.assertTrue(buf.getvalue().startswith(ccpick.PIN_GLYPH))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_ccpick.ListMarkerTests -v`
Expected: FAIL with `TypeError: print_list() got an unexpected keyword argument 'marks'`

- [ ] **Step 3: Update `print_list`**

Replace `print_list` with:

```python
def print_list(metas, marks=None, show_markers=False):
    for m in metas:
        prefix = row_marker(marks, m["sessionId"]) if show_markers else ""
        print(
            f"{prefix}"
            f"{rel_time(m['lastTs']):>4}  "
            f"{pad(project_label(m['cwd']), 28)}  "
            f"{pad(m['title'], 60)}  "
            f"{m['sessionId']}"
        )
```

- [ ] **Step 4: Wire markers into the `main()` non-interactive branch**

In `main()`, replace the `if args.json or args.list:` block body:

```python
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
```

with:

```python
    if args.json or args.list:
        if query:
            metas = apply_filter(metas, query)
        if args.limit and args.limit > 0:
            metas = metas[: args.limit]
        show_markers = bool(marks.pins or marks.saved)
        if args.json:
            out = [
                dict(m, pinned=marks.is_pinned(m["sessionId"]),
                     saved=marks.is_saved(m["sessionId"]))
                for m in metas
            ]
            print(json.dumps(out, indent=2))
        else:
            print_list(metas, marks=marks, show_markers=show_markers)
        return 0
```

- [ ] **Step 5: Run tests + a manual smoke check**

Run: `python -m unittest test_ccpick.ListMarkerTests -v`
Expected: PASS (2 tests)

Then, if you have real sessions and at least one mark set from Task 4:
Run: `python ccpick.py --json | python -c "import sys,json; d=json.load(sys.stdin); print(any(x['pinned'] for x in d))"`
Expected: prints `True` when a pin exists (or `False` if none). Run: `python ccpick.py -l` and confirm pinned rows begin with `★ `.

- [ ] **Step 6: Commit**

```bash
git add ccpick.py test_ccpick.py
git commit -m "Show pin/save markers in --list and --json output"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the Features list**

In `README.md`, add a bullet to the `## Features` list (after the trash bullet ~line 55):

```markdown
- Pin sessions (default max 3, `--max-pins N`) to float them to a top group, and save others to an unlimited "save for later" group; both persist in `~/.claude/ccpick-marks.json`. Toggle with `.` then `p` / `b`. Typing a filter flattens the groups into the ranked results
```

- [ ] **Step 2: Update the interactive Keys table**

In `README.md`, add rows to the `### Keys (interactive)` table, after the `Delete` row (~line 86):

```markdown
| `.` then `p` | pin / unpin the highlighted session (top group, capped) |
| `.` then `b` | save / unsave the highlighted session ("save for later" group) |
```

- [ ] **Step 3: Update the Options table**

In `README.md`, add a row to the `## Options` table, after the `--purge-after` row (~line 141):

```markdown
| `--max-pins N` | maximum pinned sessions (default: 3) |
```

- [ ] **Step 4: Add a Notes bullet**

In `README.md`, add to the `## Notes` list:

```markdown
- Pins and saved sessions are stored by session id in `~/.claude/ccpick-marks.json`, separate from the disposable metadata cache. Pinned and saved groups show only when the filter is empty; any query collapses them into one ranked list. Trashing a session also clears its pin/save.
```

- [ ] **Step 5: Update CHANGELOG**

In `CHANGELOG.md`, add a new entry at the top of the changelog (follow the file's existing heading/format). Use the section shape already present in the file; add under an `## [Unreleased]` (or the next version) heading:

```markdown
### Added
- Pin sessions to a capped top group (`--max-pins N`, default 3) and save others to an unlimited "save for later" group, toggled in the picker with `.` then `p` / `b`. State persists in `~/.claude/ccpick-marks.json`. Groups show when the filter is empty and collapse into the ranked list while filtering. `--list` prefixes a marker glyph and `--json` gains `pinned` / `saved` booleans
```

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document pin and save-for-later"
```

---

## Self-Review

**Spec coverage:**
- Data model / persistence → Tasks 1, 2 (`Marks`, `load_marks`/`save_marks`, `MARKS_PATH`).
- Marking semantics (mutual exclusion, cap, promotion) → Task 1.
- Action mode (leader `.`, p/b, Esc, trash-disabled) → Task 4.
- Grouped rendering + header-aware navigation → Tasks 3 (pure builders) + 4 (render/scroll).
- Filter flattens / sort keeps pins in pin order → Task 4 `build_view()`.
- Trash drops marks → Task 4 `K_DEL` branch.
- `--json` booleans, `--list` glyph → Task 5.
- `--max-pins` → Task 4.
- Error handling (corrupt marks → empty, swallowed writes) → Task 2.
- Testing → Tasks 1-3, 5 unit tests; Task 4 manual checklist.
- No-marks-unchanged invariant → Task 4 `show_markers` gate (Step 6.1) + Task 5 default-off.

**Placeholder scan:** none — every code step shows complete function bodies and exact edit locations.

**Type consistency:** `Marks` method names (`is_pinned`, `is_saved`, `toggle_pin`, `toggle_save`, `drop`) and return strings (`"pinned"`, `"unpinned"`, `"cap"`, `"saved"`, `"unsaved"`) are used identically in Tasks 1, 4, 5. Row dict shape (`{"kind","label"}` / `{"kind","meta"}`) is consistent across `build_rows`, `session_row_indices`, and `render`. `render`/`interactive_select` new signatures match their single call sites.
