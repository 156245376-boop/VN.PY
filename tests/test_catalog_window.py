"""现成功能可离线浏览，不因查看示例触发交易或阻塞窗口。"""

import importlib
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import pytest


def pump_until(root, condition):
    end = time.monotonic() + 5
    while not condition() and time.monotonic() < end:
        root.update()
        time.sleep(0.01)
    assert condition()


def browse_components_and_sources(monkeypatch):
    module = importlib.import_module("qf.catalog_gui")
    inventory = {
        "ready": True, "issues": [], "sdk_version": "3.10.2", "sdk_root": "fixture-sdk",
        "ta_functions": 70, "tafunc_functions": 41, "web_assets": 45,
        "examples": ["tutorial/t01.py", "example/random_forest.py"],
        "skill": {"installed": True, "root": "fixture-skill", "files": ["SKILL.md"],
                  "missing": []},
        "example_dependencies": {"sklearn": {"installed": True, "version": "1.9.1"}},
        "capabilities": [
            {"key": "download", "title": "历史下载", "description": "官方下载工具",
             "installed": True, "integration": "已安装，按需接入",
             "permission": "需 tq_dl 专业权限",
             "doc": "https://doc.shinnytech.com/tqsdk/latest/reference/tqsdk.tools.html"},
        ],
    }
    root = tk.Tk()
    root.withdraw()
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url) or True)
    panel = module.CatalogPanel(root, inventory_fn=lambda: inventory,
                                read_fn=lambda name: "raise RuntimeError('NEVER RUN THIS')")
    panel.pack(fill="both", expand=True)
    try:
        panel.refresh()
        pump_until(root, lambda: panel.inventory is not None)
        panel.component_tree.selection_set("download")
        panel.show_component()
        assert "tq_dl" in panel.detail_text.get("1.0", "end")
        assert "按需接入" in panel.detail_text.get("1.0", "end")
        panel.doc_button.invoke()
        assert opened == [inventory["capabilities"][0]["doc"]]
        panel.example_filter.set("forest")
        panel.filter_examples()
        assert panel.example_list.get(0, "end") == ("example/random_forest.py",)
        panel.example_list.selection_set(0)
        panel.show_example()
        assert "NEVER RUN THIS" in panel.source_text.get("1.0", "end")
        assert panel.source_text.cget("state") == "disabled"
        assert "示例 2 个" in panel.summary.get()  # 数量来自实际清单。
    finally:
        root.destroy()


def check_background_failure():
    module = importlib.import_module("qf.catalog_gui")
    entered, release = threading.Event(), threading.Event()

    def check():
        entered.set()
        release.wait(3)
        raise OSError("private-unexpected-response")

    root = tk.Tk()
    root.withdraw()
    panel = module.CatalogPanel(root, inventory_fn=check)
    panel.pack()
    try:
        panel.refresh()
        assert entered.wait(1)
        assert panel.busy
        root.update()  # 检查尚未返回时仍能处理窗口事件。
        release.set()
        pump_until(root, lambda: not panel.busy)
        assert "未完成" in panel.summary.get()
        assert "private-" not in panel.detail_text.get("1.0", "end")
        assert "disabled" not in panel.refresh_button.state()
    finally:
        release.set()
        root.destroy()


@pytest.mark.parametrize("scenario", ["browse", "failure"])
def test_catalog_window_in_its_own_tcl_interpreter(scenario):
    # 与 pythonw 实际启动一致：每个进程一个 Tk。Windows Tcl 在反复销毁再创建
    # 解释器时偶发无法读取 init.tcl；进程隔离保留全部真实窗口断言，不重试或跳过。
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), scenario],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if sys.argv[1] == "browse":
        with pytest.MonkeyPatch.context() as patch:
            browse_components_and_sources(patch)
    else:
        check_background_failure()
