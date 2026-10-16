import time
import tkinter as tk

from qf.desktop import DesktopSession
from qf.gui import DesktopApp


def test_window_masks_password_runs_observer_and_stops_without_terminal(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("qf.gui.webbrowser.open", lambda url: opened.append(url) or True)

    def execute(mode, config, root, credentials, **kwargs):
        assert mode == "paper" and not kwargs["activate"]
        kwargs["progress"]("chart_ready", url="http://127.0.0.1:23456")
        kwargs["progress"]("observing", elapsed=0, duration=0)
        while not kwargs["stop_requested"]():
            time.sleep(0.01)
        return {"status": "stopped", "reason": "requested_stop"}

    root = tk.Tk()
    root.withdraw()
    session = DesktopSession(tmp_path, execute_fn=execute)
    app = DesktopApp(root, session)
    try:
        assert app.password_entry.cget("show")
        app.user.set("u")
        app.password.set("private-password")
        app.observe_button.invoke()
        end = time.monotonic() + 5
        while not opened and time.monotonic() < end:
            root.update()
            time.sleep(0.01)
        assert opened == ["http://127.0.0.1:23456"]
        assert "disabled" in app.observe_button.state()
        app.stop_button.invoke()
        session.thread.join(timeout=5)
        app.poll_messages()
        assert not session.running
        assert "已停止" in app.status.get()
        assert "private-password" not in app.log_text.get("1.0", "end")
    finally:
        session.stop()
        if session.thread:
            session.thread.join(timeout=5)
        root.destroy()
