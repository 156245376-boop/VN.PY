Option Explicit
Dim fs, shell, root, python, entry, command
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = fs.BuildPath(root, ".venv-tqsdk\Scripts\pythonw.exe")
entry = fs.BuildPath(root, "tools\workbench_entry.py")
If Not fs.FileExists(python) Then
    MsgBox "Python environment is missing. Run tools/setup.ps1 first.", 48, "TqSdk"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
command = Chr(34) & python & Chr(34) & " -I -X utf8 -B " & Chr(34) & entry & Chr(34)
shell.Run command, 0, False
