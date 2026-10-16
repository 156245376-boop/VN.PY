"""轻量本机启动窗口；行情图表继续使用天勤原生网页。"""

import os
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from qf.catalog_gui import CatalogPanel
from qf.credentials import SavedLogin
from qf.desktop import RUN_ID, DesktopSession, allowed_chart_url

STAGE_TEXT = {
    "sdk_loading": "正在加载天勤 SDK", "sdk_ready": "天勤 SDK 已就绪",
    "record_creating": "正在准备实验记录", "connecting": "正在登录并连接天勤",
    "waiting_data": "等待合约、行情和账户数据", "data_ready": "行情和账户数据已就绪",
    "backtesting": "正在运行固定历史样本", "observing": "只读观察中 · 不发送委托",
    "paper_active": "模拟策略运行中 · 最多多头 1 手", "heartbeat": "程序仍在运行",
    "stopping": "正在收尾和核对状态", "done": "正在生成结果摘要",
    "chart_ready": "天勤图形页面已就绪", "report_ready": "回测完成 · 可查看图形报告",
    "baseline_complete": "基准回测完成，开始双倍费用回测",
}
STATUS_TEXT = {"stopped": "已停止", "backtest_finished": "回测已完成",
               "data_ready": "数据已就绪", "failed": "运行未完成", "frozen": "已冻结 · 请核实状态"}
REASON_TEXT = {
    "requested_stop": "已按要求结束运行。停止执行不表示已经平仓。",
    "historical_replay_completed": "基准和双倍费用回测已执行；示例不代表策略有效。",
    "sdk_or_auth_or_permission_error": "天勤连接、认证、权限或执行未完成，请核对账号及权限。",
    "startup_or_local_record_error": "启动或本机记录失败，请检查环境与磁盘。",
    "new_run_requires_flat_account": "主模拟账户有持仓，请先核实；程序不会自动清仓。",
    "new_run_requires_no_orders": "主模拟账户有未结束委托，请先核实。",
    "cancellation_unconfirmed": "撤单尚未确认，请在快期模拟客户端核实挂单。",
    "connection_lost": "连接中断，执行已停止，请核实挂单及持仓。",
    "comparison_cancelled": "比较已取消，双倍费用回放尚未完成。",
    "double_fee_replay_failed": "双倍费用回放未完成，不能作为完整比较结果。",
    "sdk_cost_missing": "SDK 未提供完整的模拟成本，回测已停止。",
    "data_timeout_or_permission_unavailable": "数据尚未就绪或权限不足，请核对后重试。",
}


class DesktopApp:
    def __init__(self, root, session, *, credential_store=None):
        self.root, self.session = root, session
        self.chart_url = None
        self.last_result = None
        self.closing = False
        self._login = SavedLogin(session.results_root.parent, store=credential_store)
        saved = self._login.info()
        self.user = tk.StringVar(value=saved["user"])
        self.password = tk.StringVar()
        self.remember = tk.BooleanVar(value=True)
        self.credential_note = tk.StringVar(value=saved["issue"] or (
            "密码已保存，留空即可连接；也可输入新密码。" if saved["saved"]
            else "连接成功后由 Windows 安全保存，下次无需再输入。"))
        self.status = tk.StringVar(value="等待登录")
        self.elapsed = tk.StringVar(value="填写快期账号，选择要做的操作")
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll_messages)

    def _build(self):
        root = self.root
        root.title("天勤策略工作台 · 模拟与研究")
        root.geometry("1100x760")
        root.minsize(940, 680)
        root.configure(bg="#f2f5fa")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f2f5fa")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="white", foreground="#34445e",
                        font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"),
                        background="#f2f5fa", foreground="#172c4f")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("TButton", padding=(10, 9), font=("Microsoft YaHei UI", 10))
        style.configure("Primary.TButton", background="#2563eb", foreground="white")
        style.map("Primary.TButton", background=[("active", "#1d4ed8"),
                                                ("disabled", "#c3ccdc")])
        style.configure("TEntry", padding=8)
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 17, "bold"),
                        foreground="#2563eb")
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)
        header = ttk.Frame(root, padding=(26, 20))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(header, text="天勤策略工作台", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="项目提供本机操作窗口 · 行情、账户与回测图形使用天勤原生页面",
                  background="#f2f5fa").pack(anchor="w", pady=(5, 0))

        left = ttk.Frame(root, style="Card.TFrame", padding=22)
        left.grid(row=1, column=0, padx=(24, 12), pady=(0, 20), sticky="ns")
        ttk.Label(left, text="快期账户", style="Section.TLabel").pack(anchor="w")
        ttk.Label(left, text="使用天勤注册账号，非期货资金账号").pack(anchor="w", pady=(6, 12))
        ttk.Label(left, text="账号").pack(anchor="w")
        ttk.Entry(left, textvariable=self.user, width=29).pack(fill="x", pady=(4, 10))
        ttk.Label(left, text="密码").pack(anchor="w")
        self.password_entry = ttk.Entry(left, textvariable=self.password, show="●", width=29)
        self.password_entry.pack(fill="x", pady=(4, 6))
        ttk.Checkbutton(left, text="记住账号和密码", variable=self.remember).pack(anchor="w")
        ttk.Label(left, textvariable=self.credential_note, wraplength=250,
                  foreground="#778399").pack(anchor="w", pady=(4, 4))
        ttk.Button(left, text="忘记已保存的账号密码", command=self.forget_login).pack(
            fill="x", pady=(0, 10))
        self.observe_button = ttk.Button(left, text="连接并观察", style="Primary.TButton",
                                         command=lambda: self.start("paper"))
        self.observe_button.pack(fill="x", pady=4)
        self.backtest_button = ttk.Button(left, text="运行示例回测",
                                          command=lambda: self.start("backtest"))
        self.backtest_button.pack(fill="x", pady=4)
        self.trade_button = ttk.Button(left, text="启动模拟策略（允许模拟委托）",
                                       command=lambda: self.start("paper", activate=True))
        self.trade_button.pack(fill="x", pady=4)
        ttk.Separator(left).pack(fill="x", pady=16)
        self.stop_button = ttk.Button(left, text="停止运行", command=self.stop, state="disabled")
        self.stop_button.pack(fill="x", pady=4)
        ttk.Label(left, text="停止会取消执行任务，\n可能保留已有模拟持仓。",
                  foreground="#8a6542").pack(anchor="w", pady=(12, 0))
        self.start_buttons = [self.observe_button, self.backtest_button, self.trade_button]

        right = ttk.Frame(root)
        right.grid(row=1, column=1, sticky="nsew", padx=(0, 24), pady=(0, 20))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        card = ttk.Frame(right, style="Card.TFrame", padding=22)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(card, textvariable=self.status, style="Status.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=self.elapsed).pack(anchor="w", pady=(8, 0))
        ttk.Label(card, text="示例：完成分钟收盘价 > 15 期均线 → 多 1 手，否则空仓。",
                  wraplength=580, foreground="#778399").pack(anchor="w", pady=(16, 0))
        toolbar = ttk.Frame(card, style="Card.TFrame")
        toolbar.pack(anchor="w", pady=(12, 0))
        self.chart_button = ttk.Button(toolbar, text="查看天勤图表", command=self.open_chart,
                                       state="disabled")
        self.chart_button.pack(side="left", padx=(0, 10))
        ttk.Button(toolbar, text="打开实验目录", command=self.open_results).pack(side="left")
        notebook = ttk.Notebook(right)
        notebook.grid(row=1, column=0, sticky="nsew")
        log_frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        summary_frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(log_frame, text=" 运行状态 ")
        notebook.add(summary_frame, text=" 结果摘要 ")
        self.catalog = CatalogPanel(notebook)
        notebook.add(self.catalog, text=" 天勤现成功能 ")
        self.log_text = self._text_area(log_frame)
        self.summary_text = self._text_area(summary_frame)
        self._replace(self.summary_text, "完成回测或结束观察后，这里显示结果与实验记录位置。\n\n"
                      + "回测图形显示双倍费用实验；基准及两者比较保存在结果目录。\n"
                      + "示例用于验证链路，不证明盈利能力。")
        self.notebook = notebook
        self.log("窗口已准备好。先点击“连接并观察”，确认天勤行情和账户。")

    def _text_area(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        text = tk.Text(parent, wrap="word", height=16, state="disabled", bg="white", fg="#34445e",
                       relief="flat", font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        scrollbar = ttk.Scrollbar(parent, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return text

    @staticmethod
    def _replace(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", datetime.now().strftime("%H:%M:%S") + "  " + text + "\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 300:
            self.log_text.delete("1.0", "30.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start(self, mode, *, activate=False):
        try:
            if self.session.running:
                raise ValueError("已有运行中的实验。")
            credentials = self._login.resolve(self.user.get(), self.password.get())
            self._login.prepare(*credentials, self.remember.get())
            self.session.start(mode, *credentials, activate=activate)
        except ValueError as exc:
            self._login.discard()
            messagebox.showinfo("尚未开始", str(exc), parent=self.root)
            return
        self.password.set("")
        self.chart_url = None
        self.last_result = None
        self.status.set("正在启动" + ("模拟交易" if activate else ""))
        self.elapsed.set("正在准备连接，请稍候")
        self.chart_button.state(["disabled"])
        self.stop_button.configure(text="停止运行")
        self.stop_button.state(["!disabled"])
        for button in self.start_buttons:
            button.state(["disabled"])
        action = "模拟交易" if activate else "回测" if mode == "backtest" else "只读观察"
        self.log("开始" + action + "。")

    def forget_login(self):
        try:
            self._login.forget()
            self.user.set("")
            self.password.set("")
            self.credential_note.set("已忘记账号密码；当前运行不受影响。")
        except ValueError:
            self.credential_note.set("忘记账号密码未完成，请稍后重试。")

    def stop(self):
        self.session.stop()
        self.status.set("正在停止，请等待当前步骤收尾")
        self.stop_button.state(["disabled"])
        self.log("已请求停止；正在等待连接步骤完成或撤单确认。")

    def open_chart(self):
        if allowed_chart_url(self.chart_url):
            if not webbrowser.open(self.chart_url):
                self.log("请在浏览器打开本机地址：" + self.chart_url)

    def _result_directory(self):
        run_id = (self.last_result or {}).get("run_id", "")
        root = self.session.results_root.resolve()
        if RUN_ID.fullmatch(run_id):
            candidate = (root / run_id).resolve()
            if candidate.is_relative_to(root) and candidate.is_dir():
                return candidate
        return root

    def open_results(self):
        directory = self._result_directory()
        if directory.is_dir():
            os.startfile(directory)
        else:
            messagebox.showinfo("实验目录", "首次运行后会生成实验记录。", parent=self.root)

    def _show_result(self, result):
        self.last_result = result
        status = STATUS_TEXT.get(result["status"], "运行未完成")
        self.status.set(status)
        reason = REASON_TEXT.get(result.get("reason"), "请查看实验报告，核实当前状态。")
        self.elapsed.set(reason)
        self.log(status + "；" + reason)
        text = status + "\n" + reason + "\n\n"
        for key, label in (("final_equity", "末次权益"), ("commission", "回测总费用"),
                           ("day_commission", "当交易日费用")):
            if key in result:
                text += f"{label}：{result[key]:,.2f}\n"
        directory = self._result_directory()
        text += f"\n实验目录：{directory}\n"
        if result.get("run_id"):
            for filename in ("comparison.md", "report.md"):
                path = directory / filename
                if path.is_file():
                    text += "\n" + path.read_text(encoding="utf-8")[:12000] + "\n"
        self._replace(self.summary_text, text)
        self.notebook.select(1)
        self.stop_button.state(["disabled"])
        self.chart_button.state(["disabled"])
        self.chart_url = None
        for button in self.start_buttons:
            button.state(["!disabled"])

    def poll_messages(self):
        for message in self.session.drain():
            if message["type"] == "result":
                self._login.discard()
                self._show_result(message["result"])
                if self.closing:
                    self.root.destroy()
                    return
                continue
            stage = message["stage"]
            if stage in ("data_ready", "backtesting", "observing", "paper_active"):
                self._login.confirm()
                saved = self._login.info()
                self.credential_note.set(saved["issue"] or (
                    "账号密码已由 Windows 安全保存，下次无需再输入。" if saved["saved"]
                    else "本次不保存账号密码。"))
            text = STAGE_TEXT.get(stage, "正在处理")
            if stage != "heartbeat":
                self.status.set(text)
            if "elapsed" in message:
                self.elapsed.set(f"已运行 {message['elapsed']} 秒；最新行情请查看天勤图表")
            if stage == "chart_ready":
                self.chart_url = message["url"]
                self.chart_button.state(["!disabled"])
                self.open_chart()
            if stage == "report_ready":
                self.stop_button.configure(text="结束查看并保存结果")
            self.log(text + (f" · {message['elapsed']} 秒" if "elapsed" in message else ""))
        self.root.after(100, self.poll_messages)

    def close(self):
        self._login.discard()
        if self.session.running:
            self.closing = True
            self.stop()
        else:
            self.password.set("")
            self.root.destroy()


def main():
    root = tk.Tk()
    project = Path(__file__).resolve().parent.parent
    DesktopApp(root, DesktopSession(project / "results"))
    root.mainloop()
