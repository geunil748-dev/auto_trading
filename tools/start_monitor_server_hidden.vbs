Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
workspace = fso.GetParentFolderName(scriptDir)
scriptPath = fso.BuildPath(scriptDir, "start_monitor_server.ps1")

shell.CurrentDirectory = workspace

If WScript.Arguments.Count > 0 Then
    shell.Environment("PROCESS")("AUTO_TRADING_PYTHON") = WScript.Arguments(0)
End If

shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptPath & """", 0, False
