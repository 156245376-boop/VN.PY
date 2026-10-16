"""本机目录/自选原子存储；不保存报价与认证字段。"""

import json
import os
import tempfile
from pathlib import Path

from qf.market import CONTINUOUS, catalog_rows


class WorkbenchStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "settings.json"
        self._corrupt = False

    def load(self) -> dict:
        result = {"catalog": [], "favorites": [], "cache_state": "empty", "issue": ""}
        if not self.path.exists():
            return result
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(raw, dict) or not isinstance(raw.get("catalog"), list)
                    or not isinstance(raw.get("favorites"), list)
                    or not all(isinstance(r, dict) for r in raw["catalog"])):
                raise ValueError("invalid settings")
            result.update(catalog=catalog_rows(raw["catalog"]),
                          favorites=self._favorites(raw["favorites"]), cache_state="cached")
        except (OSError, ValueError, TypeError):
            self._corrupt = True
            result.update(cache_state="corrupt", issue="目录或自选文件无法读取，原文件已保留。")
        return result

    @staticmethod
    def _favorites(values):
        return list(dict.fromkeys(v for v in values if isinstance(v, str)
                                  and CONTINUOUS.fullmatch(v)))[:50]

    def save(self, catalog: list[dict], favorites: list[str]) -> None:
        if self.path.exists():
            self.load()
        if self._corrupt:
            raise ValueError("原配置已损坏，保留原文件后再处理")
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"catalog": catalog_rows(catalog), "favorites": self._favorites(favorites)}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root,
                prefix="settings-", suffix=".tmp", delete=False,
            ) as out:
                temporary = out.name
                json.dump(payload, out, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()
