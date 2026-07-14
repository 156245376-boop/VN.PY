"""实时行情网关(CTP / SimNow)。

vnpy / vnpy_ctp 为可选依赖:未安装时网关处于「不可用」状态,实时面板给出明确提示,
其余功能(历史数据、回测、矩阵、事件)照常。安装并配置连接档后,可订阅合约、
把 tick 聚合成 1s/1m K 线并通过 WebSocket 推送。

安全模式:全局开关默认开启,任何实盘自动下单请求都会被拦截。研发期只接收行情。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from app.core.config import load_connections, settings


def vnpy_available() -> bool:
    try:
        import vnpy  # type: ignore  # noqa: F401
        import vnpy_ctp  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


class BarAggregator:
    """把逐笔 tick 聚合成 1s / 1m K 线。"""

    def __init__(self, on_bar: Callable[[str, str, dict[str, Any]], None]) -> None:
        self._on_bar = on_bar
        self._sec_bars: dict[str, dict[str, Any]] = {}
        self._min_bars: dict[str, dict[str, Any]] = {}

    def update_tick(self, symbol: str, price: float, volume: float, ts: float) -> None:
        self._update(symbol, price, volume, ts, "1s", 1)
        self._update(symbol, price, volume, ts, "1m", 60)

    def _update(self, symbol: str, price: float, volume: float, ts: float, interval: str, size: int) -> None:
        store = self._sec_bars if interval == "1s" else self._min_bars
        bucket = int(ts // size) * size
        bar = store.get(symbol)
        if bar is None or bar["ts"] != bucket:
            if bar is not None:
                self._on_bar(symbol, interval, bar)
            store[symbol] = {
                "ts": bucket, "open": price, "high": price,
                "low": price, "close": price, "volume": volume,
            }
        else:
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
            bar["volume"] += volume


class GatewayService:
    """行情网关的统一门面。真实 CTP 连接在 vnpy 可用且用户点击连接后建立。"""

    def __init__(self) -> None:
        self._connected = False
        self._subscribed: set[str] = set()
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self._latest: dict[str, dict[str, Any]] = {}
        self._aggregator = BarAggregator(self._emit_bar)
        self._gateway: Any | None = None
        self._simulator: _MarketSimulator | None = None

    def status(self) -> dict[str, Any]:
        conns = load_connections()
        active = conns.get("active")
        profile = conns.get("profiles", {}).get(active, {})
        return {
            "vnpy_available": vnpy_available(),
            "connected": self._connected,
            "active_profile": active,
            "profile_kind": profile.get("kind"),
            "subscribed": sorted(self._subscribed),
            "safe_mode": settings.safe_mode,
            "mode": "real" if self._gateway is not None else ("simulated" if self._simulator else "idle"),
        }

    def add_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)

    def _broadcast(self, message: dict[str, Any]) -> None:
        for cb in list(self._listeners):
            try:
                cb(message)
            except Exception:
                pass

    def _emit_bar(self, symbol: str, interval: str, bar: dict[str, Any]) -> None:
        self._broadcast({"type": "bar", "symbol": symbol, "interval": interval, "bar": bar})

    def _emit_tick(self, symbol: str, price: float, volume: float, ts: float) -> None:
        self._latest[symbol] = {"price": price, "volume": volume, "ts": ts}
        self._broadcast({"type": "tick", "symbol": symbol, "price": price, "ts": ts})
        self._aggregator.update_tick(symbol, price, volume, ts)

    def connect(self, use_simulator_fallback: bool = True) -> dict[str, Any]:
        """连接行情源。

        vnpy 可用时尝试真实 CTP 连接;不可用且允许回落时,启动本地行情模拟器,
        让实时链路(聚合 + WebSocket 推送)在无 vnpy 环境下也能联调界面。
        """
        if vnpy_available():
            try:
                self._connect_ctp()
                self._connected = True
                return {"ok": True, "mode": "real"}
            except Exception as exc:
                return {"ok": False, "error": f"CTP 连接失败: {exc}"}
        if use_simulator_fallback:
            self._start_simulator()
            self._connected = True
            return {"ok": True, "mode": "simulated", "note": "vnpy 未安装,已启动本地行情模拟器用于界面联调"}
        return {"ok": False, "error": "vnpy 未安装,无法连接真实行情"}

    def _connect_ctp(self) -> None:
        """建立真实 CTP 连接(vnpy)。"""
        from vnpy.event import EventEngine  # type: ignore
        from vnpy.trader.engine import MainEngine  # type: ignore
        from vnpy_ctp import CtpGateway  # type: ignore

        conns = load_connections()
        active = conns.get("active")
        profile = conns["profiles"][active]
        event_engine = EventEngine()
        main_engine = MainEngine(event_engine)
        main_engine.add_gateway(CtpGateway)
        setting = {
            "用户名": profile["user_id"],
            "密码": profile["password"],
            "经纪商代码": profile["broker_id"],
            "交易服务器": profile["td_address"],
            "行情服务器": profile["md_address"],
            "产品名称": profile["app_id"],
            "授权编码": profile["auth_code"],
        }
        main_engine.connect(setting, "CTP")
        self._gateway = main_engine

    def disconnect(self) -> None:
        if self._simulator:
            self._simulator.stop()
            self._simulator = None
        if self._gateway is not None:
            try:
                self._gateway.close()
            except Exception:
                pass
            self._gateway = None
        self._connected = False

    def subscribe(self, symbol: str) -> None:
        self._subscribed.add(symbol)
        if self._simulator:
            self._simulator.add_symbol(symbol)

    def _start_simulator(self) -> None:
        if self._simulator is None:
            self._simulator = _MarketSimulator(self._emit_tick)
            self._simulator.start()

    def place_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """下单入口。安全模式下对实盘账号一律拦截。"""
        conns = load_connections()
        active = conns.get("active")
        profile = conns.get("profiles", {}).get(active, {})
        if settings.safe_mode and profile.get("kind") == "live":
            return {"ok": False, "blocked": True,
                    "reason": "安全模式已开启,禁止向实盘账号自动下单。"}
        return {"ok": False, "reason": "研发期未启用自动下单。"}


class _MarketSimulator:
    """本地行情模拟器:随机游走生成 tick,仅用于无 vnpy 时联调实时链路。"""

    def __init__(self, on_tick: Callable[[str, float, float, float], None]) -> None:
        self._on_tick = on_tick
        self._symbols: dict[str, float] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def add_symbol(self, symbol: str) -> None:
        if symbol not in self._symbols:
            self._symbols[symbol] = 3000.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        import random

        while self._running:
            now = time.time()
            for sym in list(self._symbols.keys()):
                price = self._symbols[sym]
                price = max(1.0, price * (1 + random.uniform(-0.0008, 0.0008)))
                self._symbols[sym] = price
                self._on_tick(sym, round(price, 2), random.randint(1, 20), now)
            time.sleep(0.5)


gateway = GatewayService()
