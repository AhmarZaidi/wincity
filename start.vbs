' WinCity Silent Launcher — double-clicking this file starts WinCity with zero console window
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDir
WshShell.Run "pythonw.exe """ & ScriptDir & "\main.py""", 0, False
Set WshShell = Nothing
Set FSO = Nothing
