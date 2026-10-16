import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/workbench_entry.py"


def test_new_entry_isolates_environment_and_uses_project_runtime():
    assert ENTRY.is_file(), "new workbench entry is not implemented"
    env = os.environ.copy()
    for key in ("TQ_USER", "TQ_PASSWORD", "TQ_AUTH", "TQ_ACTION", "PYTHONPATH"):
        env[key] = "private-fixture"
    code = r'''
import json, os, runpy, sys
from pathlib import Path
namespace=runpy.run_path(sys.argv[1],run_name='entry_fixture')
identity=namespace['verify_environment'](namespace['ROOT']/'.venv-tqsdk')
keys=('TQ_USER','TQ_PASSWORD','TQ_AUTH','TQ_ACTION','PYTHONPATH')
assert not any(k in os.environ for k in keys)
assert Path(identity['executable']).is_relative_to(namespace['ROOT']/'.venv-tqsdk')
print(json.dumps({'isolated':True,'sdk':identity['tqsdk']}))
'''
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", "-c", code, str(ENTRY)],
                            env=env, capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(result.stdout) == {"isolated": True, "sdk": "3.10.2"}


def test_missing_webview_runtime_is_actionable_without_account_output():
    assert ENTRY.is_file(), "new workbench entry is not implemented"
    code = r'''
import json, runpy, sys
from types import SimpleNamespace
messages=[]
def fail(): raise RuntimeError('private-token')
sys.modules['qf.workbench']=SimpleNamespace(main=fail)
sys.modules['tkinter']=SimpleNamespace(Tk=lambda:SimpleNamespace(withdraw=lambda:None,destroy=lambda:None))
sys.modules['tkinter.messagebox']=SimpleNamespace(showerror=lambda title,text:messages.append(text))
sys.modules['tkinter'].messagebox=sys.modules['tkinter.messagebox']
try: runpy.run_path(sys.argv[1],run_name='__main__')
except SystemExit as exc: assert exc.code==1
assert messages and 'WebView2' in messages[0] and 'private-' not in messages[0]
print(json.dumps({'masked':True}))
'''
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", "-c", code, str(ENTRY)],
                            capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"masked": True}


def test_launcher_opens_workbench_and_retains_legacy_entry():
    assert ENTRY.is_file(), "new workbench entry is not implemented"
    assert (ROOT / "tools/gui_entry.py").is_file()
    script = r'''
$ErrorActionPreference='Stop'
$launcher=Start-Process -FilePath wscript.exe -ArgumentList '"LAUNCHER"' `
    -WindowStyle Hidden -PassThru
$owned=[Collections.Generic.HashSet[int]]::new()
$null=$owned.Add($launcher.Id)
$window=$null
$end=[DateTime]::UtcNow.AddSeconds(18)
try {
    while ([DateTime]::UtcNow -lt $end -and -not $window) {
        foreach ($parentId in @($owned)) {
            $children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId = $parentId")
            foreach ($child in $children) {
                $null=$owned.Add([int]$child.ProcessId)
                $candidate=Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
                if ($candidate -and $candidate.MainWindowTitle -eq '天勤策略工作台 · 研究与模拟') {
                    $window=$candidate
                }
            }
        }
        Start-Sleep -Milliseconds 150
    }
    $opened=($null -ne $window)
} finally {
    foreach ($processId in @($owned)) {
        $candidate=Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.MainWindowHandle -ne 0) {
            $null=$candidate.CloseMainWindow()
            $null=$candidate.WaitForExit(6000)
        }
    }
}
$closed=($window -and $window.HasExited)
@{opened=$opened;closed=[bool]$closed}|ConvertTo-Json -Compress
'''.replace("LAUNCHER", str(ROOT / "启动天勤.vbs").replace("'", "''"))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=35, check=True,
    )
    assert json.loads(result.stdout) == {"opened": True, "closed": True}
