# claude-session-picker (ccpick)

Interactive picker to resume any Claude Code session from any project.

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
| type | filter (fuzzy, token-AND substring) |
| Up / Down | move cursor |
| PgUp / PgDn | page |
| Home / End | jump to top / bottom |
| Tab | cycle sort mode |
| Backspace | edit filter |
| Enter | resume selected session |
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

## Notes

- The picker launches `claude --resume <id>` with the working directory set to
  the session's recorded `cwd`. If that directory no longer exists it prints the
  manual resume command instead.
- The metadata cache lives at `~/.claude/ccpick-cache.json` and is rebuilt from
  scratch each run (stale entries for deleted sessions are dropped), reusing
  entries whose file mtime and size are unchanged.
