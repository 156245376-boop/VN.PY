"""本机研究结果的 SSD 工作目录与一次性迁移。"""

import os
import shutil
from pathlib import Path

APP_DIRECTORY = 'TqStrategyWorkbench'


def preferred_results_root(project_root: Path) -> Path:
    configured = os.environ.get('QF_RESULTS_ROOT')
    if configured:
        target = Path(configured).expanduser()
        if not target.is_absolute():
            raise ValueError('QF_RESULTS_ROOT 必须是绝对路径')
        return target.resolve()
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA')
        if base:
            return (Path(base)/APP_DIRECTORY/'results').resolve()
    return (Path(project_root)/'results').resolve()


def prepare_results_root(project_root: Path) -> Path:
    source = (Path(project_root)/'results').resolve()
    target = preferred_results_root(project_root)
    target.mkdir(parents=True, exist_ok=True)
    if source != target and source.is_dir():
        for item in source.iterdir():
            destination = target/item.name
            if destination.exists():
                continue
            try:
                if item.is_dir():
                    shutil.copytree(item, destination)
                elif item.is_file():
                    shutil.copy2(item, destination)
            except OSError:
                # 旧结果迁移失败不能阻止工作台启动；原目录保持不动。
                continue
    return target
