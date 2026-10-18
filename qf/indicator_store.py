"""与布局文件分开的指标偏好；原子写入，不存行情。"""

import copy
import json
import os
import tempfile
from pathlib import Path

from qf.indicator_catalog import default_item, validate_item


def default_indicators() -> dict:
    return {'schema': 1, 'panes': {f'pane-{i}': {'items': [default_item('volume'),
            default_item('oi')]} for i in range(1, 5)}}


def validate_indicator_config(raw: object) -> dict:
    if (not isinstance(raw, dict) or set(raw) != {'schema', 'panes'}
            or type(raw['schema']) is not int or raw['schema'] != 1
            or not isinstance(raw['panes'], dict)
            or set(raw['panes']) != {f'pane-{i}' for i in range(1, 5)}):
        raise ValueError('指标设置格式无效')
    for pane in raw['panes'].values():
        if (not isinstance(pane, dict) or set(pane) != {'items'}
                or not isinstance(pane['items'], list) or len(pane['items']) > 15):
            raise ValueError('每格指标设置无效')
        seen = set()
        for item in pane['items']:
            value = validate_item(item)
            if value['id'] in seen:
                raise ValueError('同一指标不能重复添加')
            seen.add(value['id'])
    return copy.deepcopy(raw)


class IndicatorStore:
    def __init__(self, root: Path):
        self.path = root / 'chart-indicators.json'

    def load(self) -> dict:
        if not self.path.exists():
            return {'config': default_indicators(), 'issue': ''}
        try:
            return {'config': validate_indicator_config(json.loads(
                self.path.read_text('utf-8'))), 'issue': ''}
        except (OSError, ValueError, TypeError):
            return {'config': default_indicators(),
                    'issue': '指标设置无法读取，已保留原文件，暂不保存新设置。'}

    def save(self, config: dict) -> None:
        payload = validate_indicator_config(config)
        if self.load()['issue']:
            raise ValueError('原指标设置损坏，已保留')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    dir=self.path.parent, prefix='indicators-', suffix='.tmp', delete=False) as out:
                temporary = Path(out.name)
                json.dump(payload, out, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
