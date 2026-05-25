Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\auto_trading\tools\start_monitor_server.ps1""", 0, False
