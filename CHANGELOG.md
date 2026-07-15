# Changelog

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
