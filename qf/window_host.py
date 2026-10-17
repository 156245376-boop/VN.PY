"""独立 WebView2 主窗口；仅可信主页面具有业务桥接。"""

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from qf.desktop import allowed_chart_url


class WindowHostError(RuntimeError):
    pass


def show_chart(url: str) -> str:
    """校验内嵌图形地址；由页面 iframe 展示，不创建带桥接的外部窗口。"""
    if not allowed_chart_url(url):
        raise ValueError("仅允许当前本机天勤图形地址")
    return url


def _install_chart_labels(window):
    """只适配本机子页的显示与历史图形，保持 SDK 安装文件与业务标识原样。"""
    try:
        from System import Action

        location = urlsplit(window.get_current_url())
        if location.scheme != "http" or location.hostname != "127.0.0.1":
            raise ValueError("工作台来源无效")
        origin = f"{location.scheme}://{location.netloc}"
        assets = Path(__file__).with_name("web")
        script = ("(() => {if(window.parent===window || location.protocol!=='http:' || "
                  "location.hostname!=='127.0.0.1')return;const qfParentOrigin="
                  + json.dumps(origin) + ";\n"
                  + (assets / "labels.js").read_text(encoding="utf-8") + "\n"
                  + (assets / "native-history.js").read_text(encoding="utf-8") + "\n"
                  + (assets / "native-labels.js").read_text(encoding="utf-8") + "\n})();")
        tasks = []
        window.native.Invoke(Action(lambda: tasks.append(
            window.native.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(script))))
        if not tasks[0].Wait(5000):
            raise TimeoutError("中文标签未就绪")
        window.evaluate_js("window.dispatchEvent(new Event('qf-native-labels-ready'))")
    except Exception:
        window.evaluate_js("window.dispatchEvent(new Event('qf-native-labels-error'))")


def run_window(page: Path, bridge, request_close, *, webview_module=None):
    if not page.is_file():
        raise WindowHostError("本机工作台页面缺失，请核对项目文件。")
    if webview_module is None:
        import webview as webview_module
    window = webview_module.create_window(
        "天勤策略工作台 · 研究与模拟", str(page.resolve()), js_api=bridge,
        width=1280, height=820, min_size=(960, 680), text_select=True,
    )
    waiting = threading.Event()
    allow_close = threading.Event()

    def finish_close():
        if window.events.loaded.is_set():
            try:
                window.evaluate_js("window.qfPrepareExit?.()")
            except Exception:
                pass  # 页面尚未就绪或已销毁时，后台清理仍须继续。
        while not request_close():
            time.sleep(0.1)
        allow_close.set()
        window.destroy()

    def closing():
        if allow_close.is_set():
            return True
        if waiting.is_set():
            return False
        if not window.create_confirmation_dialog("确认退出", "确定退出天勤策略工作台吗？"):
            return False
        waiting.set()
        threading.Thread(target=finish_close, daemon=True).start()
        return False

    window.events.closing += closing
    window.events.loaded += lambda: _install_chart_labels(window)
    try:
        webview_module.start(gui="edgechromium", debug=False, http_server=True,
                             private_mode=True)
    except Exception:
        raise WindowHostError("独立窗口启动失败，请检查 Microsoft Edge WebView2 运行时。") from None
