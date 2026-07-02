#!/usr/bin/env pwsh
# Launcher for ccpick.py. Put this file's folder on your PATH (or set an alias)
# and run `ccpick` from anywhere. Passes all arguments through to the script.
$script = Join-Path $PSScriptRoot 'ccpick.py'
& python $script @args
exit $LASTEXITCODE
