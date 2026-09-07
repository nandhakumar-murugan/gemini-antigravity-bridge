Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\smnk2\.gemini\antigravity\scratch\antigravity-mcp-bridge"
WshShell.Run """C:\Users\smnk2\AppData\Local\Programs\Python\Python313\pythonw.exe"" run_with_tunnel.py", 0, False
