# claude-session-picker (ccpick)

Interactive picker to resume any Claude Code session from any project.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Quick start

Clone the repo, then install a `ccpick` alias for your shell so you never
type `python ccpick.py` again.

**Windows (PowerShell)**

```powershell
git clone https://github.com/giovi321/claude-session-picker.git
cd claude-session-picker
./install.ps1
. $PROFILE
```

**macOS / Linux (bash or zsh)**

```sh
git clone https://github.com/giovi321/claude-session-picker.git
cd claude-session-picker
./install.sh
source ~/.zshrc   # or ~/.bashrc -- whichever the installer picked
```

Then from any directory, on any OS:

```
ccpick
```

See [Install as a `ccpick` quick command](#install-as-a-ccpick-quick-command)
below for what the installers do, how to uninstall, and manual alternatives.

Claude Code stores one JSONL transcript per session under
`~/.claude/projects/<encoded-project-dir>/<session-id>.jsonl`. The built-in
`claude --resume` (and `/resume`) only lists sessions for the current working
directory. `ccpick` scans every project, lets you fuzzy-filter and pick a
session interactively, then resumes it in its original directory.

## Features

- Scans all projects under `~/.claude/projects` (skips nested subagent/workflow transcripts)
- Live fuzzy filter across title, project path, git branch and first prompt
- Sorted by last activity by default; cycle sort with Tab (recent / oldest / project / title)
- Shows title (custom name, then AI title, then first prompt), relative time, project and branch
- Footer preview of the selected session's directory and first prompt
- On select: launches `claude --resume <id>` in the session's original directory
- Head+tail parsing never loads multi-MB transcripts fully; results cached by mtime+size so repeat launches are instant
- Zero third-party dependencies (Python 3 standard library), works on Windows and POSIX
- Delete a session to a recoverable trash folder (`Delete` key); browse/restore trash with `--trash`; auto-purges after a configurable retention period
- Pin sessions (default max 3, `--max-pins N`) to float them to a top group, and save others to an unlimited "save for later" group; both persist in `~/.claude/ccpick-marks.json`. Toggle with `.` then `p` / `b`. Typing a filter flattens the groups into the ranked results

## Requirements

- Python 3.8+
- `claude` CLI on `PATH`

## Usage

```
python ccpick.py                 # interactive picker
python ccpick.py obsidian n8n    # start with a filter query pre-typed
python ccpick.py -p myproject    # only sessions whose directory contains "myproject"
python ccpick.py -l              # print matches, no picker
python ccpick.py -l -n 20        # print the 20 most recent
python ccpick.py --json          # dump session metadata as JSON
python ccpick.py --no-launch     # print the cd + resume command instead of launching
python ccpick.py --refresh       # ignore the cache and rescan
```

### Keys (interactive)

| Key | Action |
| --- | --- |
| type | filter (fuzzy subsequence, token-AND) |
| Up / Down | move cursor |
| PgUp / PgDn | page |
| Home / End | jump to top / bottom |
| Tab | cycle sort mode |
| Backspace | edit filter |
| Enter | resume selected session |
| Delete | delete the highlighted session (moves to trash; permanently removes in `--trash` mode) |
| `.` then `p` | pin / unpin the highlighted session (top group, capped) |
| `.` then `b` | save / unsave the highlighted session ("save for later" group) |
| Esc / Ctrl-C | cancel |

## Install as a `ccpick` quick command

The installers add a `ccpick` function to your shell profile so you can run
`ccpick` from anywhere. They are re-runnable (the managed block between the
`# >>> ccpick >>>` / `# <<< ccpick <<<` markers is replaced in place) and
resolve the script path relative to themselves, so they work wherever you
cloned the repo.

Windows (PowerShell) — adds a `ccpick` function to `$PROFILE`:

```powershell
./install.ps1
. $PROFILE      # reload, then:  ccpick
```

POSIX (zsh / bash) — adds a `ccpick` function to your shell rc (auto-detected
from `$SHELL`; override with `--rc <file>`):

```sh
./install.sh
source ~/.zshrc   # or ~/.bashrc; then:  ccpick
```

To uninstall, delete the marked block from your profile / rc.

### Manual alternatives

PowerShell — define the function yourself:

```powershell
function ccpick { & python "Z:\git\claude-session-picker\ccpick.py" @args }
```

POSIX — symlink the launcher onto your `PATH`:

```sh
ln -s /path/to/claude-session-picker/ccpick.sh ~/.local/bin/ccpick
```

## Options

| Flag | Meaning |
| --- | --- |
| `query...` | initial filter query |
| `-l`, `--list` | print matches and exit (no picker) |
| `--json` | dump session metadata as JSON and exit |
| `-p`, `--project SUBSTR` | only sessions whose directory contains SUBSTR |
| `-s`, `--sort {recent,oldest,project,title}` | sort order (default: recent) |
| `-n`, `--limit N` | show at most N sessions |
| `--refresh` | ignore the metadata cache and rescan |
| `--no-launch` | print the `cd` + resume command instead of launching |
| `--trash` | browse trash instead of live sessions (`Enter` restores, `Delete` permanently removes) |
| `--purge-after N` | trash retention in days before auto-purge (default: 30) |
| `--max-pins N` | maximum pinned sessions (default: 3) |

## Notes

- The picker launches `claude --resume <id>` with the working directory set to
  the session's recorded `cwd`. If that directory no longer exists it prints the
  manual resume command instead.
- The metadata cache lives at `~/.claude/ccpick-cache.json` and is rebuilt from
  scratch each run (stale entries for deleted sessions are dropped), reusing
  entries whose file mtime and size are unchanged.
- Deleted sessions move to `~/.claude/ccpick-trash/` (mirroring the live layout) rather than being removed immediately; browse and restore them with `ccpick --trash`. Expired trash (older than `--purge-after` days, default 30) is purged automatically at the start of every run.
- Pins and saved sessions are stored by session id in `~/.claude/ccpick-marks.json`, separate from the disposable metadata cache. Pinned and saved groups show only when the filter is empty; any query collapses them into one ranked list. Trashing a session also clears its pin/save.
