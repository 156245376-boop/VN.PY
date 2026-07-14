"""REST 路由:连接配置、系统状态、历史数据、事件、回测、场景矩阵、策略。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.core.compute import gpu_info
from app.core.config import load_connections, redact_profile, save_connections, settings
from app.models.schemas import (
    BacktestRequest,
    DownloadRequest,
    EventItem,
    MatrixRequest,
)
from app.services import (
    backtest_service,
    data_service,
    event_service,
    matrix_service,
    strategies,
)
from app.services.gateway_service import gateway

router = APIRouter(prefix="/api")


# ---- 系统 / GPU / 安全模式 ----

@router.get("/system/status")
def system_status() -> dict[str, Any]:
    info = gpu_info()
    return {
        "app": settings.app_name,
        "version": settings.version,
        "safe_mode": settings.safe_mode,
        "gpu": info.__dict__,
        "akshare_available": data_service.akshare_available(),
        "gateway": gateway.status(),
    }


class SafeModeBody(BaseModel):
    enabled: bool


@router.post("/system/safe-mode")
def set_safe_mode(body: SafeModeBody) -> dict[str, Any]:
    settings.safe_mode = body.enabled
    return {"safe_mode": settings.safe_mode}


# ---- 连接配置(敏感信息脱敏返回) ----

@router.get("/connections")
def get_connections() -> dict[str, Any]:
    conns = load_connections()
    profiles = {
        key: redact_profile(p) for key, p in conns.get("profiles", {}).items()
    }
    return {"active": conns.get("active"), "profiles": profiles}


class ConnectionUpdate(BaseModel):
    key: str
    profile: dict[str, Any]


@router.put("/connections")
def update_connection(body: ConnectionUpdate) -> dict[str, Any]:
    conns = load_connections()
    profiles = conns.setdefault("profiles", {})
    existing = profiles.get(body.key, {})
    # 若传入为脱敏占位符,保留原值,避免覆盖真实密钥。
    merged = dict(existing)
    for k, v in body.profile.items():
        if v == "******":
            continue
        merged[k] = v
    profiles[body.key] = merged
    save_connections(conns)
    return {"ok": True, "key": body.key}


class ActiveBody(BaseModel):
    key: str


@router.post("/connections/active")
def set_active(body: ActiveBody) -> dict[str, Any]:
    conns = load_connections()
    if body.key not in conns.get("profiles", {}):
        raise HTTPException(404, f"连接档不存在: {body.key}")
    conns["active"] = body.key
    save_connections(conns)
    return {"active": body.key}


# ---- 行情网关 ----

@router.post("/gateway/connect")
def gateway_connect() -> dict[str, Any]:
    return gateway.connect()


@router.post("/gateway/disconnect")
def gateway_disconnect() -> dict[str, Any]:
    gateway.disconnect()
    return {"ok": True}


class SubscribeBody(BaseModel):
    symbol: str


@router.post("/gateway/subscribe")
def gateway_subscribe(body: SubscribeBody) -> dict[str, Any]:
    gateway.subscribe(body.symbol)
    return {"ok": True, "subscribed": sorted(gateway._subscribed)}


# ---- 历史数据 ----

@router.get("/data/symbols")
def data_symbols() -> list[dict[str, Any]]:
    return [s.model_dump() for s in data_service.list_symbols()]


@router.get("/data/bars")
def data_bars(symbol: str, interval: str = "1m", start: str | None = None,
              end: str | None = None, limit: int = 5000) -> dict[str, Any]:
    bars = data_service.get_bars(symbol, interval, start, end, limit)
    return {
        "symbol": symbol,
        "interval": interval,
        "bars": [b.model_dump() for b in bars],
    }


@router.post("/data/download")
def data_download(req: DownloadRequest) -> dict[str, Any]:
    try:
        return data_service.download(req.symbol, req.start, req.end, req.interval)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@router.post("/data/import-csv")
async def data_import_csv(symbol: str, file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    try:
        return data_service.import_csv(symbol, content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---- 事件日历 ----

@router.get("/events")
def events_list(category: str | None = None) -> list[dict[str, Any]]:
    return [e.model_dump() for e in event_service.list_events(category)]


@router.post("/events")
def events_add(event: EventItem) -> dict[str, Any]:
    return event_service.add_event(event).model_dump()


@router.delete("/events/{event_id}")
def events_delete(event_id: int) -> dict[str, Any]:
    ok = event_service.delete_event(event_id)
    if not ok:
        raise HTTPException(404, "事件不存在")
    return {"ok": True}


@router.post("/events/seed")
def events_seed() -> dict[str, Any]:
    return {"added": event_service.seed_events()}


class AnomalyBody(BaseModel):
    symbol: str
    sigma: float = 3.0


@router.post("/events/detect-anomalies")
def events_detect(body: AnomalyBody) -> dict[str, Any]:
    bars = data_service.get_bars(body.symbol, "1d", limit=10_000_000)
    detected = event_service.detect_anomalies(body.symbol, bars, body.sigma)
    return {"detected": [e.model_dump() for e in detected]}


# ---- 策略 / 回测 / 场景矩阵 ----

@router.get("/strategies")
def strategies_list() -> list[dict[str, Any]]:
    return [s.model_dump() for s in strategies.list_strategies()]


@router.post("/backtest")
def run_backtest(req: BacktestRequest) -> dict[str, Any]:
    try:
        return backtest_service.run_backtest(req).model_dump()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/matrix")
def run_matrix(req: MatrixRequest) -> dict[str, Any]:
    return matrix_service.run_matrix(req).model_dump()
