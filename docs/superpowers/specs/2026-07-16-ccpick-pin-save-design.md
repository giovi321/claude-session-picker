# ccpick: pin + save-for-later (phase 3)

## Goal

Add two durable per-session markings to the interactive picker, inside the
existing single-file tool:

1. Pin — a small, capped set of sessions that float to the very top of the
   list (default max 3, `--max-pins N`).
2. Save-for-later ("bookmark") — an unlimited watchlist shown as its own
   group directly below the pins, above the normal session list.

Both survive across runs (the tool's first durable user state), render as
their own grouped sections when no filter is active, and collapse into the
normal fuzzy-ranked flat list the moment a query is typed.

## Non-goals

- No true side panel / split layout — a terminal TUI has no room for one;
  "on the side" is realized as the SAVED group below PINNED.
- No manual reordering of pins within the pinned group (pins render in the
  order they were pinned). Deferred; YAGNI for now.
- No cap or truncation of the saved group.
- No regrouping in `--list` output (stays a flat sorted list; markers only).

## Constraints carried over from the existing project

- Zero third-party dependencies — Python 3 standard library only.
- Works on both Windows (msvcrt) and POSIX (raw termios) key handling paths.
- The mtime+size metadata cache (`~/.claude/ccpick-cache.json`) stays
  disposable/rebuilt-each-run. Durable user state (marks) is a *separate*
  file so a cache wipe never loses pins.

## Data model & persistence

New file `~/.claude/ccpick-marks.json`:

```json
{ "v": 1, "pins": ["<sessionId>", "..."], "saved": ["<sessionId>", "..."] }
```

- Keyed by `sessionId` (the transcript filename's UUID) — globally unique,
  stable, and independent of the encoded-project-dir path, so it survives
  cache rebuilds and is unaffected by the lossy `decode_project_dir`.
- `pins` is an ordered list; its order *is* the pinned-group display order.
- `saved` is stored as a list (insertion order) but rendered in the active
  sort mode.
- Atomic write: `tmp` file + `os.replace`, mirroring `save_cache`.
- Loaded once at startup into an in-memory `Marks` structure; rewritten on
  every mark mutation.

### Load/save helpers

- `load_marks() -> Marks` — reads and validates the file; on missing,
  unreadable, wrong-version, or malformed content returns an empty `Marks`
  (same defensive posture as `load_cache`). Version mismatch is treated as
  empty rather than migrated (no prior version exists).
- `save_marks(marks)` — atomic write; any `OSError` is swallowed like
  `save_cache`.

`Marks` is a light object (or dict) exposing ordered `pins` / `saved`
`sessionId` lists plus mutation helpers (see below). Pure and
TTY-independent so it is unit-testable.

## Marking semantics

Pin and save are **mutually exclusive** per session. Mutations operate on a
`sessionId`:

- `toggle_pin(sid, max_pins)`:
  - If already pinned → unpin (session returns to normal). Returns a result
    indicating "unpinned".
  - Else, if `len(pins) >= max_pins` → refuse; no state change. Returns a
    result indicating "cap reached" so the caller can show the footer note
    `N pins max — unpin one first`.
  - Else → add to `pins` (append, preserving order); if it was in `saved`,
    remove it there (promotion). Returns "pinned".
- `toggle_save(sid)`:
  - If already saved → unsave. Returns "unsaved".
  - Else → add to `saved`; if it was in `pins`, remove it there. Returns
    "saved".
- `is_pinned(sid)` / `is_saved(sid)` — membership tests used during
  rendering and for the `--json` / `--list` marker columns.
- `drop(sid)` — remove `sid` from both lists (used when a session is
  trashed).

Dangling marks (a `sessionId` with no matching live session in the current
scan) remain in the file and are simply not rendered; if the session is
later restored from trash it re-resolves and the mark reappears.

## Action mode (leader key)

A transient mode entered from the picker:

- Leader key `.` enters action mode. The footer shows
  `[p]in  [b]ookmark   Esc` (dim/bold styling reusing existing ANSI
  constants).
- In action mode:
  - `p` → `toggle_pin` on the highlighted session, then leave the mode and
    persist. Footer briefly reflects the outcome (`pinned` / `unpinned` /
    `N pins max — unpin one first`).
  - `b` → `toggle_save` on the highlighted session, then leave and persist
    (`saved` / `unsaved`).
  - `Esc`, or any other key → leave the mode with no change (the other key
    is consumed, not applied to the filter).
- Consequence: a literal `.` can no longer be typed into the filter query.
  Accepted — the fuzzy matcher already treats `.` as a separator, so it is
  not needed as a search character.
- Disabled in `--trash` mode (marks are meaningless there): `.` is ignored.

Implementation: a small boolean state in the `interactive_select` loop
(`action_mode`), not a nested read loop, so a single `read_key()` per
iteration is preserved and the screen redraws (with the action footer)
between the leader press and the action key.

## Grouped rendering & navigation

### Rows model

A new pure builder produces the ordered list of display rows the picker
draws and navigates:

`build_rows(pinned_metas, saved_metas, other_metas, grouped) -> [Row]`

where each `Row` is either:

- a **header** row (`kind="header"`, non-selectable), or
- a **session** row (`kind="session"`, holds a `meta`, selectable).

- When `grouped` is true (empty query AND at least one resolvable mark):
  rows are `[HEADER "PINNED", <pins…>, HEADER "SAVED FOR LATER", <saved…>,
  HEADER "── sessions ──", <others…>]`. A group with no members omits both
  its header and its rows. If there are zero marks, `grouped` is false and
  there are no header rows at all — the picker is byte-for-byte today's.
- When `grouped` is false (any non-empty query, or `--trash` mode): a single
  flat list of session rows, exactly today's ordering (`apply_filter`
  ranked, or the sort mode).

### Cursor / scroll over headers

`interactive_select` navigates over the rows list, but the cursor may only
land on selectable (session) rows:

- Movement (`Up`/`Down`/`PgUp`/`PgDn`/`Home`/`End`) skips header rows —
  e.g. `Down` advances to the next session row, stepping over any headers.
- The viewport (`top`/`rows`) counts header rows as occupying a line
  (they render and scroll) but they are never the cursor target.
- `Enter` acts on the highlighted session row; action mode acts on it too.
- Helper functions keep this contained: e.g. `first_session_index(rows)`,
  `next_session(rows, i, step)`, so the main loop's arithmetic stays
  readable and is unit-testable without a TTY.

### Row rendering

- Header rows: dim, uppercase label (`PINNED`, `SAVED FOR LATER`,
  `── sessions ──`), cleared to full width.
- Session rows: as today (time / project / title, inverse when highlighted,
  fuzzy highlight when filtering) plus a leading one-cell marker glyph:
  `★ ` pinned, `◆ ` saved, two spaces otherwise, so columns stay aligned.
  The glyph is drawn in every mode (grouped, flat, highlighted).
- The footer detail/preview area is unchanged.

## Filter / sort interaction

- Non-empty query → flat mode (grouping off), existing fuzzy rank preserved.
  Marker glyphs still show on matching rows.
- Empty query → grouped mode (if any mark resolves).
- `Tab` sort: reorders the SAVED group and the bottom (`── sessions ──`)
  group by the active sort mode; the PINNED group always stays in pin order.
  Cursor tries to stay on the same session across a sort/group rebuild, same
  as today's `keep = view[cursor]` behavior.

## Trash & mark lifecycle

- Trashing a session via `Delete` (existing behavior) additionally calls
  `marks.drop(sid)` and persists — a trashed conversation must not hold a
  pin slot or clutter the saved group.
- Restoring from `--trash` does **not** re-add any mark (the user re-pins if
  they still want it). Judgment call, flagged for review.
- Permanent delete in `--trash` mode: no mark interaction needed (marks were
  already dropped at trash time).

## Non-interactive surfaces

- `--json`: every emitted meta gains `"pinned": bool` and `"saved": bool`.
  Order unchanged.
- `--list`: a leading two-cell marker column (`★ ` / `◆ ` / spaces) prefixes
  each row; ordering unchanged (still the flat sorted list), so existing
  scripts that parse columns see a stable, prepended marker only.

## CLI surface added

| Flag | Meaning |
| --- | --- |
| `--max-pins N` | maximum pinned sessions (default: 3) |

## Keybindings added (interactive picker, live mode only)

| Key | Action |
| --- | --- |
| `.` | enter action mode (`[p]in [b]ookmark  Esc`) |
| `.` then `p` | toggle pin on the highlighted session (refused at cap) |
| `.` then `b` | toggle save-for-later on the highlighted session |
| `.` then `Esc`/other | leave action mode, no change |

## Error handling

- Corrupt/unreadable/missing `ccpick-marks.json` → empty marks (no crash),
  same as the cache.
- Any `OSError` writing marks → swallowed (a lost mark write is non-fatal);
  the picker continues.
- Marks referencing sessions absent from the current scan are silently
  unresolved (not rendered), never an error.
- The pin cap is enforced in `toggle_pin`; over-cap attempts change nothing
  and surface only as a footer note.

## Testing

Extend `test_ccpick.py` (stdlib `unittest`) with pure, TTY-independent
coverage:

- `load_marks` / `save_marks` round-trip, including malformed/empty/
  wrong-version files → empty marks.
- `toggle_pin` / `toggle_save`: mutual exclusion (pin promotes a saved item
  and vice-versa), unpin/unsave, and cap enforcement (refuse at `max_pins`,
  including a custom cap).
- `build_rows`: grouped output shape (headers present, empty groups omitted,
  no doubling of a marked session into the bottom group), flat output when
  not grouped, and grouped=false when there are zero marks.
- Navigation helpers: `next_session` / `first_session_index` skip header
  rows correctly (top, bottom, adjacent headers, all-header edge cases).
- Dangling-mark resolution: a `sessionId` not present in the scan does not
  appear and does not raise.

Interactive keystrokes (leader → p/b, cap footer, grouped vs flat toggle,
marker glyphs, Windows + POSIX) verified manually per the existing
convention — the TUI has no automated harness.
