' FundPilot AI: start the website in the background with no window at all.
' (start.cmd does the same but briefly flashes a console window.)
Option Explicit
Dim shell, folder
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
' Use the React frontend unless FUNDPILOT_FRONTEND is already set (legacy restores the old pages).
Dim env
Set env = shell.Environment("Process")
If env("FUNDPILOT_FRONTEND") = "" Then env("FUNDPILOT_FRONTEND") = "react"
shell.Run """" & folder & "\runtime\python.exe"" -B """ & folder & "\launch.py"" --reload --background", 0, False
