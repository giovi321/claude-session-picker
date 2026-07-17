# Changelog

## v0.2.0

- Pin sessions to a capped top group (`--max-pins N`, default 3) and save others to an unlimited "save for later" group, toggled in the picker with `.` then `p` / `b` (a `.=pin/save` hint shows in the header); state persists in `~/.claude/ccpick-marks.json`, separate from the disposable metadata cache
- Pinned and saved sessions render as their own groups when the filter is empty and collapse into the ranked list while filtering; `--list` prefixes a marker glyph and `--json` gains `pinned` / `saved` booleans

## v0.1.1

- Fix `project_label()` unconditionally rendering with a backslash separator, which showed paths like `giovanni\project` on macOS/Linux instead of `giovanni/project`. The project column now always displays with the current platform's native separator regardless of how the path was recorded.

## v0.1.0

Initial release.

- Interactive picker that scans every `~/.claude/projects` transcript (not just the current directory) and resumes the chosen session with `claude --resume`
- Fuzzy subsequence search (fzf/Obsidian-style) across title, project path, git branch and first prompt, with matched-character highlighting
- Sort by recent / oldest / project / title, cycled with Tab
- Delete a session to a recoverable trash folder (`Delete` key, inline confirm); browse and restore trash with `--trash`; expired trash auto-purges (`--purge-after`, default 30 days)
- Non-interactive modes: `-l`/`--list`, `--json`, `-p`/`--project`, `--no-launch`
- Metadata cache keyed by file mtime+size so repeat launches are instant
- Zero third-party dependencies (Python 3 standard library only), works on Windows and POSIX
- Install scripts for PowerShell and POSIX shells
