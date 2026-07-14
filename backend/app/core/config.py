"""应用配置与路径管理。

连接档(账号、密码、AppID、授权码)属于敏感信息,单独存放在 git 忽略的
config/connections.json 中,不写入代码库。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# 项目根目录:backend/app/core/config.py -> backend/ -> 项目根
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = BACKEND_DIR / "config"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "market.db"
CONNECTIONS_PATH = CONFIG_DIR / "connections.json"


class Settings(BaseModel):
    """运行期设置。"""

    app_name: str = "草老师的交易系统"
    version: str = "0.1.0"
    db_path: str = str(DB_PATH)
    # 安全模式:默认开启,禁止向实盘自动下单。
    safe_mode: bool = True
    # 允许的跨域来源(前端 dev server)。
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]


settings = Settings()


# ---- 连接档持久化(敏感信息,单独文件) ----

_DEFAULT_CONNECTIONS: dict[str, Any] = {
    "active": "simnow",
    "profiles": {
        "simnow": {
            "name": "SimNow 仿真",
            "kind": "simulation",
            "broker_id": "9999",
            "user_id": "",
            "password": "",
            "app_id": "simnow_client_test",
            "auth_code": "0000000000000000",
            "md_address": "tcp://182.254.243.31:30011",
            "td_address": "tcp://182.254.243.31:30001",
        },
        "huaxi": {
            "name": "华西期货(实盘)",
            "kind": "live",
            "broker_id": "",
            "user_id": "",
            "password": "",
            "app_id": "",
            "auth_code": "",
            "md_address": "",
            "td_address": "",
        },
    },
}


def load_connections() -> dict[str, Any]:
    """读取连接档;不存在时返回默认模板(含 SimNow 与实盘占位)。"""
    if CONNECTIONS_PATH.exists():
        try:
            return json.loads(CONNECTIONS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(_DEFAULT_CONNECTIONS))
    return json.loads(json.dumps(_DEFAULT_CONNECTIONS))


def save_connections(data: dict[str, Any]) -> None:
    """写入连接档到 git 忽略的敏感文件。"""
    CONNECTIONS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def redact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """脱敏:对外返回连接档时隐藏密码与授权码。"""
    redacted = dict(profile)
    for key in ("password", "auth_code"):
        if redacted.get(key):
            redacted[key] = "******"
    return redacted
