Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c uv run python main.py", 0, False
