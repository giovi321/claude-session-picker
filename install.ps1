#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Install ccpick as a PowerShell quick command.
.DESCRIPTION
    Adds (or updates) a `ccpick` function in your PowerShell profile that runs
    ccpick.py from this folder. Re-runnable: the managed block between the
    ccpick markers is replaced in place, so running it again just refreshes it.
.PARAMETER ProfilePath
    Profile file to edit. Defaults to $PROFILE (current user, current host).
.EXAMPLE
    ./install.ps1
    . $PROFILE      # reload, then run:  ccpick
#>
param([string]$ProfilePath = $PROFILE)

$ErrorActionPreference = 'Stop'

$script = Join-Path $PSScriptRoot 'ccpick.py'
if (-not (Test-Path $script)) { throw "ccpick.py not found next to installer: $script" }
$script = (Resolve-Path $script).Path

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Warning "python was not found on PATH. Install Python 3, or the ccpick function will not run."
}

$begin = '# >>> ccpick >>>'
$end   = '# <<< ccpick <<<'
$block = @"
$begin
# Interactive Claude Code session picker (personal-helpers). Managed by install.ps1.
function ccpick { & python "$script" @args }
$end
"@

# Ensure the profile file (and its directory) exists.
$dir = Split-Path -Parent $ProfilePath
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
if (-not (Test-Path $ProfilePath)) { New-Item -ItemType File -Path $ProfilePath | Out-Null }

$content = Get-Content -Raw -Path $ProfilePath -ErrorAction SilentlyContinue
if ($null -eq $content) { $content = '' }

$pattern = [regex]::Escape($begin) + '.*?' + [regex]::Escape($end)
$rx = [regex]::new($pattern, [System.Text.RegularExpressions.RegexOptions]::Singleline)
if ($rx.IsMatch($content)) {
    $content = $rx.Replace($content, { param($m) $block }, 1)
    $action = 'Updated'
} else {
    if ($content -and -not $content.EndsWith("`n")) { $content += "`r`n" }
    $content += "`r`n$block`r`n"
    $action = 'Added'
}

Set-Content -Path $ProfilePath -Value $content -NoNewline -Encoding UTF8

Write-Host "$action ccpick function in: $ProfilePath"
Write-Host "Reload it with:  . `$PROFILE   (or open a new terminal), then run:  ccpick"
