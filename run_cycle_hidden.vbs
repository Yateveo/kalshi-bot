' Launches run_cycle.ps1 completely invisibly. Task Scheduler's own
' -WindowStyle Hidden on powershell.exe is unreliable and can still flash
' or show a window; wscript.exe's Run with windowStyle=0 does not.
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""F:\Trading\run_cycle.ps1""", 0, False
