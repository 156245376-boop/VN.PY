"""公开TOML实验修订；原子落盘，任何已保存版本不可被修改。"""

import json
import os
import re
import tempfile
import tomllib
import uuid
from pathlib import Path

from qf.journal import PaperLock
from qf.research_config import ResearchConfig, migrate_to_pivot, validate_research_config


def _toml(data, section=''):
    lines = [f'[{section}]'] if section else []
    for key, value in data.items():
        if isinstance(value, dict) or value is None:
            continue
        lines.append(f'{key} = {json.dumps(value, ensure_ascii=False)}')
    for key, value in data.items():
        if isinstance(value, dict):
            lines.extend(['', _toml(value, f'{section}.{key}' if section else key)])
    return '\n'.join(lines) + '\n'


class ExperimentStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _folder(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
            raise ValueError('实验编号无效')
        folder = self.root / identity
        if not folder.resolve().is_relative_to(self.root):
            raise ValueError('实验位置无效')
        return folder

    def _read(self, identity, revision):
        if type(revision) is not int or revision < 1:
            raise ValueError('实验修订无效')
        path = self._folder(identity) / f'{revision}.toml'
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('实验位置无效')
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
        if (set(raw) - {'experiment_id', 'revision', 'parent', 'config'}
                or raw.get('experiment_id') != identity or raw.get('revision') != revision):
            raise ValueError('实验文件无效')
        validate_research_config(raw['config'])
        parent = raw.get('parent')
        if parent is not None:
            if set(parent) != {'experiment_id', 'revision'}:
                raise ValueError('实验来源无效')
            self._folder(parent['experiment_id'])
            if type(parent['revision']) is not int or parent['revision'] < 1:
                raise ValueError('实验来源无效')
        return raw

    def load(self, experiment_id: str, revision: int) -> ResearchConfig:
        return validate_research_config(self._read(experiment_id, revision)['config'])

    def list(self):
        result = []
        if not self.root.exists():
            return result
        for folder in sorted(self.root.iterdir()):
            if not re.fullmatch('[0-9a-f]{32}', folder.name) or not folder.is_dir():
                continue
            versions = [int(p.stem) for p in folder.glob('*.toml') if p.stem.isdigit()]
            if versions:
                try:
                    raw = self._read(folder.name, max(versions))
                    result.append(dict(experiment_id=folder.name, revision=max(versions),
                                       parent=raw.get('parent'), config=raw['config']))
                except (OSError, ValueError, KeyError, TypeError):
                    result.append(dict(experiment_id=folder.name, issue='实验文件无法读取'))
        return result

    def save(self, config: ResearchConfig, *, experiment_id=None):
        return self._save(config, experiment_id=experiment_id)

    def _save(self, config, *, experiment_id=None, parent=None):
        config = validate_research_config(config.public())
        self.root.mkdir(parents=True, exist_ok=True)
        # 复用内核文件锁；此根目录与模拟账户锁目录不同。
        with PaperLock(self.root):
            identity = experiment_id or uuid.uuid4().hex
            folder = self._folder(identity)
            if experiment_id and not folder.is_dir():
                raise ValueError('实验不存在')
            folder.mkdir(exist_ok=True)
            versions = [int(p.stem) for p in folder.glob('*.toml') if p.stem.isdigit()]
            revision = max(versions, default=0) + 1
            if versions:
                parent = self._read(identity, max(versions)).get('parent')
            raw = dict(experiment_id=identity, revision=revision, parent=parent,
                       config=config.public())
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                                 suffix='.tmp', delete=False) as out:
                    temporary = Path(out.name)
                    out.write(_toml(raw))
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, folder / f'{revision}.toml')
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            return {k: raw[k] for k in ('experiment_id', 'revision', 'parent')}

    def copy(self, experiment_id, revision, *, name, upgrade_to_pivot=False,
             upgrade_to_continuous=False):
        if (type(upgrade_to_pivot) is not bool or type(upgrade_to_continuous) is not bool
                or (upgrade_to_pivot and upgrade_to_continuous)):
            raise ValueError('升级选项无效')
        config = self.load(experiment_id, revision)
        if upgrade_to_continuous:
            from qf.continuous_config import migrate_to_continuous
            config = migrate_to_continuous(config, name=name)
        elif upgrade_to_pivot:
            config = migrate_to_pivot(config, name=name)
        raw = config.public()
        raw['name'] = name
        return self._save(validate_research_config(raw),
                          parent=dict(experiment_id=experiment_id, revision=revision))
