$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
# *>> defaults to UTF-16LE in Windows PowerShell 5.1, which garbles the log
# for anything reading it as UTF-8 (tail, most editors). Pipe through
# Out-File -Encoding utf8 instead so the log is actually readable.
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\main.py" *>&1 |
    Out-File -FilePath "$PSScriptRoot\cycle.log" -Append -Encoding utf8
