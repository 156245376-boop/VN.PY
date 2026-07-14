# 草老师的交易系统

国内期货量化研发平台。研发期用「自建 Web 界面 + vnpy 引擎」,核心能力是用 GPU 做
**场景矩阵回测**:同一策略在多品种 × 多周期 × 多事件/时段过滤 × 多参数组合下的批量并行验证与对比。

## 设计原则:优雅降级

平台的纯 Python 部分(历史数据、回测、事件日历、场景矩阵)不依赖任何重型库即可运行。
以下能力按「检测到就启用,没有就回落」工作:

- `vnpy` / `vnpy_ctp`:用于 SimNow / 实盘 CTP 实时行情。未安装时,实时行情面板提示不可用,其余功能照常。
- `CuPy`:用于 GPU 加速场景矩阵。未安装或无 GPU 时,自动回落到 NumPy(CPU)。
- `akshare`:用于在线下载历史数据。未安装时,仍可用 CSV 导入。

因此即使 Python 3.12 与重型依赖尚未装好,应用也能启动、界面可看、CSV 回测可跑。

## 目录结构

```
backend/            FastAPI 后端
  app/
    core/           配置、数据库、GPU 后端检测
    models/         Pydantic 模型
    services/       数据 / 回测 / 场景矩阵 / 事件日历 / 行情网关
    api/            REST + WebSocket 路由
  tests/            pytest
frontend/           Vite + React + TypeScript 前端
data/               SQLite 数据库与本地数据(git 忽略)
```

## 环境要求

- Python 3.12(vnpy 兼容 3.10-3.13;当前机器默认 3.14 无法安装 vnpy,需单独装 3.12)
- Node.js 18+

## 快速开始

### 后端

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-core.txt      # 纯 Python 核心,先跑起来
# 可选(需 Python 3.12):
# pip install -r requirements-live.txt     # vnpy + CTP 实时行情
# pip install cupy-cuda12x                  # GPU 加速(RTX 3060 / CUDA 12+)
uvicorn app.main:app --reload --port 8180
```

### 前端

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开前端给出的地址(默认 http://localhost:5173)。

## 交易安全

研发期默认开启「安全模式」,禁止向实盘自动下单。实盘账号(如华西期货)需要
穿透式监管的 AppID 与授权码,向期货公司申请后填入连接配置。SimNow 为免费仿真环境,
用于研发期实时行情联调。

## 数据来源说明

- 历史数据:akshare 在线下载或本地 CSV 导入,落地 SQLite,可按任意周期重采样。
- 实时行情:CTP(SimNow/实盘),交易所每 500ms 一笔,实时最小 K 线实用为 1s/1m。
- 事件日历:用户可编辑事件区间 + 自动异常波动检测 + 预置宏观事件种子。
