"""有限四格配置与本机原子存储；不保存连接、行情或凭证。"""

import copy
import json
import math
import os
import tempfile
from pathlib import Path

from qf.market import CONTINUOUS

PANE_IDS = {f"pane-{i}" for i in range(1, 5)}
PERIODS = {"close": 60, "1m": 60, "5m": 300, "15m": 900,
           "30m": 1800, "1h": 3600, "1d": 86400}


def default_workspace() -> dict:
    return {"schema": 1, "layout": "single", "active": "pane-1", "linked": False,
            "split": {"column": .5, "row": .5}, "account_collapsed": False,
            "panes": [{"id": f"pane-{i}", "continuous": None, "mode": "actual",
                       "period": None} for i in range(1, 5)]}


def period_for(pane: dict) -> str:
    return pane.get("period") or ("1d" if pane["mode"] == "continuous" else "1m")


def validate_panes(raw: object, *, requests=False) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 4:
        raise ValueError("图表最多四格")
    result, seen = [], set()
    fields = {"id", "continuous", "mode", "period"} | ({"revision"} if requests else set())
    for pane in raw:
        if not isinstance(pane, dict) or set(pane) != fields:
            raise ValueError("图表字段无效")
        ident, symbol, period = pane["id"], pane["continuous"], pane["period"]
        if (not isinstance(ident, str) or ident not in PANE_IDS or ident in seen
                or symbol is not None and (not isinstance(symbol, str)
                                           or not CONTINUOUS.fullmatch(symbol))
                or pane["mode"] not in ("actual", "continuous")
                or period is not None and (not isinstance(period, str) or period not in PERIODS)):
            raise ValueError("图表设置无效")
        if requests and (type(pane["revision"]) is not int
                         or not 0 < pane["revision"] <= 2**53 - 1):
            raise ValueError("图表版本无效")
        seen.add(ident)
        result.append(copy.deepcopy(pane))
    return result


def validate_workspace(raw: object) -> dict:
    default = default_workspace()
    if not isinstance(raw, dict) or set(raw) != set(default):
        raise ValueError("工作区字段无效")
    if (type(raw["schema"]) is not int or raw["schema"] != 1
            or raw["layout"] not in ("single", "columns", "rows", "quad")
            or not isinstance(raw["active"], str) or raw["active"] not in PANE_IDS
            or type(raw["linked"]) is not bool or type(raw["account_collapsed"]) is not bool):
        raise ValueError("工作区设置无效")
    split = raw["split"]
    if (not isinstance(split, dict) or set(split) != {"row", "column"}
            or any(type(n) not in (int, float) or not math.isfinite(n) or not .1 <= n <= .9
                   for n in split.values())):
        raise ValueError("分屏比例无效")
    panes = validate_panes(raw["panes"])
    if len(panes) != 4:
        raise ValueError("工作区需要四个固定格")
    return copy.deepcopy(raw)


class ChartWorkspaceStore:
    def __init__(self, root: Path):
        self.path = root / "chart-workspace.json"

    def load(self) -> dict:
        if not self.path.exists():
            return {"workspace": default_workspace(), "issue": ""}
        try:
            workspace = validate_workspace(json.loads(self.path.read_text(encoding="utf-8")))
            return {"workspace": workspace, "issue": ""}
        except (OSError, ValueError, TypeError):
            return {"workspace": default_workspace(),
                    "issue": "布局文件无法读取，已保留原文件并使用默认布局；新布局暂不保存。"}

    def save(self, workspace: dict) -> None:
        payload = validate_workspace(workspace)
        if self.load()["issue"]:
            raise ValueError("原布局文件损坏，已保留")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="chart-", suffix=".tmp", delete=False) as out:
                temporary = Path(out.name)
                json.dump(payload, out, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
