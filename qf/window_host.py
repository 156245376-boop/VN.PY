"""独立 WebView2 主窗口；仅可信主页面具有业务桥接。"""

import threading
import time
from pathlib import Path

from qf.desktop import allowed_chart_url


class WindowHostError(RuntimeError):
    pass


def show_chart(url: str) -> str:
    """校验内嵌图形地址；由页面 iframe 展示，不创建带桥接的外部窗口。"""
    if not allowed_chart_url(url):
        raise ValueError("仅允许当前本机天勤图形地址")
    return url


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

    def finish_close():
        while not request_close():
            time.sleep(0.1)
        window.destroy()

    def closing():
        if request_close():
            return True
        if not waiting.is_set():
            waiting.set()
            threading.Thread(target=finish_close, daemon=True).start()
        return False

    window.events.closing += closing
    try:
        webview_module.start(gui="edgechromium", debug=False, http_server=True,
                             private_mode=True)
    except Exception:
        raise WindowHostError("独立窗口启动失败，请检查 Microsoft Edge WebView2 运行时。") from None
