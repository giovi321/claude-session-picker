# ccpick: delete + fuzzy search (phase 1)

## Goal

Extend `ccpick` with two capabilities inside the existing single-file
interactive picker:

1. Delete a session (soft-delete to a recoverable trash location).
2. Replace today's token-AND substring filter with true fuzzy subsequence
   matching (Obsidian quick-switcher / fzf style), including highlighting of
   matched characters in the rendered title.

## Non-goals (deferred to phase 2)

A conversational "ask Claude which sessions to delete" mode is a separate
sub-project with its own spec, built on top of the manual delete primitive
defined here. Not designed or implemented in this phase.

## Constraints carried over from the existing project

- Zero third-party dependencies — Python 3 standard library only.
- Works on both Windows (msvcrt) and POSIX (raw termios) key handling paths.
- No persisted config file; anything configurable is a CLI flag with a
  sensible default.

## Fuzzy matching

### Algorithm

`fuzzy_score(token, haystack) -> (score, matched_indices) | None`, a
hand-rolled subsequence scorer (fzf/Sublime style), using dynamic programming
to find the *optimal* alignment of `token`'s characters inside `haystack`
(not just the first alignment found). Scoring bonuses/penalties:

- Bonus for contiguous runs of matched characters.
- Bonus when a match starts right after a separator (space, `/`, `\`, `-`,
  `_`) — rewards word-boundary matches.
- Bonus for a match at position 0.
- Small penalty per unmatched character skipped between matches (gap
  penalty).

Returns `None` when `token`'s characters cannot be found in order at all
(no match), otherwise a numeric score (lower = better, consistent with the
existing `match()`/`apply_filter()` convention) and the list of matched
character indices in `haystack`.

### Integration

- `match(query, m)` splits `query` on whitespace as it does today, but each
  token is now scored via `fuzzy_score` against `haystack(m)` instead of
  `str.find`. All tokens must match (AND semantics preserved); the session's
  total score is the sum of per-token scores. No match on any token means the
  session is excluded, same as today.
- Highlighting is computed separately and only against `m["title"]`: for each
  query token, `fuzzy_score(token, m["title"])` is attempted; the union of
  all tokens' matched indices (when present) is passed to `render()` so it
  can bold/color those character positions when drawing the title. A token
  that matched only in `cwd`/`gitBranch`/`firstPrompt` (not in the title)
  still lets the session pass the filter — it just adds no highlight marks,
  since the title is the only field rendered under highlighting.

### Rendering

`render()` draws the title character-by-character when highlight indices are
present for that row, wrapping matched characters in `BOLD`+`CYAN` (reusing
existing ANSI constants) and leaving the rest as today's plain/inverse
styling. Non-highlighted rows render exactly as before — no behavior change
when the query is empty.

## Delete + trash + restore

### Trash layout

`~/.claude/ccpick-trash/<same-encoded-project-dir>/<session-id>.jsonl` —
mirrors the live `~/.claude/projects/<encoded-project-dir>/<session-id>.jsonl`
layout exactly. This means:

- Restoring is a plain file move back to the mirrored path; the original
  project association is never lost or reconstructed.
- No separate trash manifest/index file is needed to track "where did this
  come from."

On move into trash, `os.utime()` stamps the file's mtime to the current
time, so "how long has this been in trash" is answered directly by the
filesystem mtime — still no manifest file required.

### Deleting (live picker)

New key `K_DEL`:

- Windows: the `Delete` key's scan code (`"S"` in `_WIN_SPECIAL`) moves from
  its current mapping (`K_BS`, treated as backspace) to a new `K_DEL`.
  Backspace remains the only way to edit the filter text.
- POSIX: the `\x1b[3~` escape sequence maps to `K_DEL` in `_POSIX_SEQ`.

On `K_DEL` with a session highlighted, the footer shows an inline confirm:
`Delete "<title>"? y/N` (single keypress via the existing `read_key()`;
anything other than `y`/`Y` — including `Esc` and `Ctrl-C` — cancels the
confirm only, returning to the normal picker view rather than exiting the
whole program). On confirm, the session's `.jsonl` moves to its mirrored
trash path and is removed from `all_metas`/`view` in place (cursor/top
adjust the same way a filter change already does) — no rescan or cache
invalidation needed beyond dropping the one entry.

### Trash browsing / restore (`--trash`)

A new CLI flag `--trash` scans the trash directory (via the existing
`parse_session`, since trashed files are byte-for-byte untouched JSONL) and
opens the same `interactive_select`/`render` machinery against those metas,
with two behavior differences inside this mode:

- `Enter` restores: moves the file back to its mirrored live path (recreating
  the `~/.claude/projects/<encoded-dir>/` directory if needed) instead of
  launching `claude --resume`.
- `K_DEL` permanently deletes: removes the file outright (no double-trash),
  behind the same inline `y/N` confirm.

The footer/preview rendering is unchanged; only the meaning of `Enter` and
`K_DEL`, and the data source, differ in this mode.

### Auto-purge

A sweep runs at the top of `main()` on every invocation — interactive mode,
`--list`, `--json`, and `--trash` alike — walking the trash directory and
permanently deleting any file whose mtime is older than the retention
period. Retention is `--purge-after N` (days), default `30`, not persisted
between runs. Silent when nothing is purged; a one-line stderr message when
something was (`purged N expired trash session(s)`).

## Error handling

- Restoring into a project directory that no longer exists still succeeds:
  the `.jsonl` moves back under a freshly-created
  `~/.claude/projects/<encoded-dir>/`; the existing `resume()` already
  handles a missing `cwd` at resume time by printing the manual resume
  command instead of failing.
- Any OSError while moving/deleting a single file during a manual
  delete/restore/purge is caught, reported to stderr, and does not abort the
  picker or the batch purge sweep — same defensive pattern the existing scan
  loop uses for unreadable transcripts.

## Testing

No existing automated test suite (single-file interactive script). This
phase adds:

- `test_ccpick.py` (stdlib `unittest`) covering the pure, TTY-independent
  functions: `fuzzy_score` (match/no-match cases, bonus ordering, matched
  index correctness), the trash path mapping (encode/mirror/restore round
  trip), and the purge-age threshold check.
- Manual keyboard-driven verification of delete / restore / purge / fuzzy
  highlighting in a real terminal (PowerShell on Windows at minimum; POSIX
  if available) — the TUI itself has no automated harness.

## CLI surface added

| Flag | Meaning |
| --- | --- |
| `--trash` | browse trash instead of live sessions; `Enter` restores, `Delete` key permanently removes |
| `--purge-after N` | trash retention in days before auto-purge (default: 30) |

## Keybindings added (interactive picker, both live and `--trash` modes)

| Key | Live picker | `--trash` mode |
| --- | --- | --- |
| `Delete` | soft-delete to trash (confirm) | permanently delete (confirm) |
| `Enter` | resume (unchanged) | restore to live projects dir |
