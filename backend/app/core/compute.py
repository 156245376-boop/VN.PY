"""计算后端检测与选择。

GPU(CuPy)用于场景矩阵的大规模并行回测。若 CuPy 或 GPU 不可用,自动回落到
NumPy(CPU)。对外暴露统一的数组模块 `xp`,调用方无需关心底层是 GPU 还是 CPU。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class GpuInfo:
    """GPU 可用性与显存信息。"""

    available: bool
    name: str | None = None
    total_mem_mb: float | None = None
    free_mem_mb: float | None = None
    used_mem_mb: float | None = None
    cuda_version: str | None = None
    reason: str | None = None  # 不可用原因


_cupy_module: Any | None = None
_cupy_checked = False


def _try_import_cupy() -> Any | None:
    """尝试导入 CuPy 并做一次最小的设备探测。"""
    global _cupy_module, _cupy_checked
    if _cupy_checked:
        return _cupy_module
    _cupy_checked = True
    try:
        import cupy as cp  # type: ignore

        # 触发一次设备访问,确认驱动/运行时确实可用。
        cp.cuda.runtime.getDeviceCount()
        _cupy_module = cp
    except Exception:
        _cupy_module = None
    return _cupy_module


def gpu_info() -> GpuInfo:
    """返回当前 GPU 状态(型号、显存占用)。"""
    cp = _try_import_cupy()
    if cp is None:
        return GpuInfo(available=False, reason="CuPy 未安装或无可用 CUDA 设备")
    try:
        device = cp.cuda.Device(0)
        props = cp.cuda.runtime.getDeviceProperties(0)
        name = props["name"].decode() if isinstance(props["name"], bytes) else str(props["name"])
        free_b, total_b = cp.cuda.runtime.memGetInfo()
        used_b = total_b - free_b
        runtime_ver = cp.cuda.runtime.runtimeGetVersion()
        cuda_version = f"{runtime_ver // 1000}.{(runtime_ver % 1000) // 10}"
        with device:
            pass
        return GpuInfo(
            available=True,
            name=name,
            total_mem_mb=round(total_b / 1024 / 1024, 1),
            free_mem_mb=round(free_b / 1024 / 1024, 1),
            used_mem_mb=round(used_b / 1024 / 1024, 1),
            cuda_version=cuda_version,
        )
    except Exception as exc:  # 探测失败时安全回落
        return GpuInfo(available=False, reason=f"GPU 探测失败: {exc}")


def get_backend(prefer_gpu: bool) -> tuple[Any, str]:
    """返回 (数组模块, 后端名)。

    prefer_gpu 为真且 GPU 可用时返回 CuPy,否则返回 NumPy。
    """
    if prefer_gpu:
        cp = _try_import_cupy()
        if cp is not None:
            return cp, "gpu"
    return np, "cpu"


def to_numpy(array: Any) -> np.ndarray:
    """把可能是 CuPy 的数组转回 NumPy(用于返回结果)。"""
    cp = _cupy_module
    if cp is not None and isinstance(array, cp.ndarray):
        return cp.asnumpy(array)
    return np.asarray(array)
