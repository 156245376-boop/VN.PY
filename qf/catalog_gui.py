"""SDK 现成组件、官方示例与技能入口；只读、不建立账户会话。"""

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk
from urllib.parse import urlparse


class CatalogPanel(ttk.Frame):
    def __init__(self, parent, *, inventory_fn=None, read_fn=None):
        super().__init__(parent, padding=10)
        self.inventory_fn, self.read_fn = inventory_fn, read_fn
        self.inventory = None
        self.busy = False
        self.messages = queue.Queue()
        self.timer = None
        self.summary = tk.StringVar(value="无需登录即可检查和浏览天勤已安装资源。")
        self.example_filter = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew")
        self.refresh_button = ttk.Button(toolbar, text="检查已安装资源", command=self.refresh)
        self.refresh_button.pack(side="left")
        ttk.Label(toolbar, text="只读检查 · 不登录、不运行示例",
                  background="#f2f5fa").pack(side="left", padx=8)
        ttk.Label(self, textvariable=self.summary, wraplength=600,
                  background="#f2f5fa").grid(row=1, column=0, sticky="w", pady=8)
        tabs = ttk.Notebook(self)
        tabs.grid(row=2, column=0, sticky="nsew")
        components, examples, resources = (ttk.Frame(tabs, padding=6) for _ in range(3))
        tabs.add(components, text="功能目录")
        tabs.add(examples, text="官方示例源码")
        tabs.add(resources, text="技能与资源")
        components.columnconfigure(0, weight=1)
        components.rowconfigure(0, weight=1)
        components.rowconfigure(1, weight=1)
        self.component_tree = ttk.Treeview(components, columns=("installed", "integration"),
                                           selectmode="browse", height=3)
        self.component_tree.heading("#0", text="天勤原生能力")
        self.component_tree.heading("installed", text="本机组件")
        self.component_tree.heading("integration", text="项目使用状态")
        self.component_tree.column("#0", width=210, minwidth=130)
        self.component_tree.column("installed", width=70, minwidth=60, stretch=False)
        self.component_tree.column("integration", width=170, minwidth=130)
        self.component_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(components, command=self.component_tree.yview)
        self.component_tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")
        self.component_tree.bind("<<TreeviewSelect>>", lambda _: self.show_component())
        detail = ttk.Frame(components)
        detail.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self.detail_text = self._text(detail, height=3)
        self.doc_button = ttk.Button(components, text="打开选中功能的官方文档",
                                      command=self.open_doc, state="disabled")
        self.doc_button.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        examples.columnconfigure(0, weight=1)
        examples.rowconfigure(2, weight=1)
        ttk.Label(examples, text="原版示例只供参考：可能含旧合约、占位凭证或其他交易逻辑。",
                  wraplength=580).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(examples, textvariable=self.example_filter).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=6)
        self.example_filter.trace_add("write", lambda *_: self.filter_examples())
        self.example_list = tk.Listbox(examples, width=25, height=4, exportselection=False)
        self.example_list.grid(row=2, column=0, sticky="nsew")
        example_scroll = ttk.Scrollbar(examples, command=self.example_list.yview)
        self.example_list.configure(yscrollcommand=example_scroll.set)
        example_scroll.grid(row=2, column=1, sticky="ns")
        self.example_list.bind("<<ListboxSelect>>", lambda _: self.show_example())
        ttk.Button(examples, text="查看选中源码", command=self.show_example).grid(
            row=3, column=0, sticky="w", pady=(6, 0))
        self.source_window = None
        self.source_text = None
        self.resource_text = self._text(resources, height=10)
        self.bind("<Map>", self._on_map)
        self.bind("<Destroy>", self._on_destroy)

    @staticmethod
    def _text(parent, *, height):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        text = tk.Text(parent, wrap="word", height=height, state="disabled", bg="white",
                       fg="#34445e", relief="flat", padx=8, pady=8)
        scroll = ttk.Scrollbar(parent, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return text

    @staticmethod
    def _replace(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", value)
        widget.configure(state="disabled")

    def _on_map(self, event):
        if event.widget is self and self.inventory is None and not self.busy:
            self.refresh()

    def _on_destroy(self, event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.refresh_button.state(["disabled"])
        self.summary.set("正在离线校验组件、示例与网页资源……")
        threading.Thread(target=self._check, daemon=True).start()
        self.timer = self.after(100, self._poll)

    def _check(self):
        try:
            if self.inventory_fn is None:
                from qf.native_catalog import inspect_installation
                result = inspect_installation()
            else:
                result = self.inventory_fn()
            self.messages.put(result)
        except Exception:
            self.messages.put(None)

    def _poll(self):
        self.timer = None
        try:
            inventory = self.messages.get_nowait()
        except queue.Empty:
            self.timer = self.after(100, self._poll)
            return
        self.busy = False
        self.refresh_button.state(["!disabled"])
        if inventory is None:
            self.summary.set("资源检查未完成，请运行 tools/check.ps1 核对本机环境。")
            self._replace(self.detail_text, "可通过 tools/setup.ps1 重新安装锁定环境。")
            return
        self.inventory = inventory
        state = "离线资源就绪" if inventory["ready"] else "发现资源缺失或损坏"
        self.summary.set(f"{state} · TqSdk {inventory['sdk_version']} · "
                         f"示例 {len(inventory['examples'])} 个\n"
                         f"指标 {inventory['ta_functions']} 个 · "
                         f"序列函数 {inventory['tafunc_functions']} 个 · "
                         f"网页资源 {inventory['web_assets']} 个；权限需联网另验。")
        self.component_tree.delete(*self.component_tree.get_children())
        for capability in inventory["capabilities"]:
            self.component_tree.insert("", "end", iid=capability["key"], text=capability["title"],
                                       values=("已安装" if capability["installed"] else "缺失",
                                               capability["integration"]))
        self.filter_examples()
        skill = inventory["skill"]
        sklearn = inventory["example_dependencies"]["sklearn"]
        text = ("本机登录窗口与按钮由项目提供；浏览器图表、账户展示与回测图形来自天勤。\n\n"
                f"SDK：{inventory['sdk_root']}\n"
                f"官方技能：{skill['root']}\n"
                f"技能文件：{len(skill['files'])} 个；缺失：{len(skill['missing'])} 个\n"
                f"官方示例额外依赖 scikit-learn：{sklearn.get('version') or '未安装'}\n\n"
                "示例和网页使用 SDK 原版资源，不复制到项目源码。技能是使用说明，不是客户端。\n"
                "已安装不等于已授权或已验证策略；专业服务和独立客户端需单独开通。\n")
        if inventory["issues"]:
            text += "\n检查问题：\n" + "\n".join(inventory["issues"])
        self._replace(self.resource_text, text)
        items = self.component_tree.get_children()
        if items:
            self.component_tree.selection_set(items[0])
            self.show_component()

    def _selected_component(self):
        selection = self.component_tree.selection()
        if self.inventory and selection:
            return next((c for c in self.inventory["capabilities"] if c["key"] == selection[0]),
                        None)
        return None

    def show_component(self):
        capability = self._selected_component()
        if capability is None:
            self.doc_button.state(["disabled"])
            return
        text = (f"{capability['title']}\n{capability['description']}\n\n"
                f"项目状态：{capability['integration']}\n"
                f"权限与限制：{capability['permission']}\n\n{capability['doc']}")
        self._replace(self.detail_text, text)
        self.doc_button.state(["!disabled"])

    def open_doc(self):
        capability = self._selected_component()
        if capability:
            url = capability["doc"]
            parsed = urlparse(url)
            if (parsed.scheme == "https" and parsed.hostname in
                    {"doc.shinnytech.com", "www.shinnytech.com"}
                    and not parsed.username and not parsed.password):
                webbrowser.open(url)

    def filter_examples(self):
        self.example_list.delete(0, "end")
        if self.inventory:
            query = self.example_filter.get().strip().casefold()
            for name in self.inventory["examples"]:
                if query in name.casefold():
                    self.example_list.insert("end", name)

    def show_example(self):
        selected = self.example_list.curselection()
        if not selected:
            return
        name = self.example_list.get(selected[0])
        try:
            if self.read_fn is None:
                from qf.native_catalog import read_example
                source = read_example(name)
            else:
                source = self.read_fn(name)
        except (OSError, ValueError):
            self._replace(self.detail_text, "示例源码无法读取，请重新检查已安装资源。")
            return
        if self.source_window is None or not self.source_window.winfo_exists():
            self.source_window = tk.Toplevel(self)
            self.source_window.geometry("1000x700")
            self.source_text = self._text(self.source_window, height=30)
            self.source_text.configure(wrap="none", font=("Consolas", 10))
            horizontal = ttk.Scrollbar(self.source_window, orient="horizontal",
                                       command=self.source_text.xview)
            self.source_text.configure(xscrollcommand=horizontal.set)
            horizontal.grid(row=1, column=0, sticky="ew")
        self.source_window.title("官方示例 · 只读参考 · " + name)
        self._replace(self.source_text, source)
        self.source_window.lift()
