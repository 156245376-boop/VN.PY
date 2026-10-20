"""可信桌面页面的最小业务桥接；不向网页暴露文件或命令执行接口。"""

import math
import re
import subprocess
import threading
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from qf.chart_workspace import PERIODS, ChartWorkspaceStore, period_for, validate_panes
from qf.credentials import SavedLogin
from qf.desktop import allowed_chart_url
from qf.experiment_store import ExperimentStore
from qf.history import HISTORY_ISSUES
from qf.indicator_catalog import indicator_catalog
from qf.indicator_jobs import IndicatorJobs
from qf.indicator_store import IndicatorStore, default_indicators
from qf.market import catalog_rows
from qf.market_account import public_account
from qf.market_session import MarketSession
from qf.market_units import price_unit
from qf.replay_view import ReplayView
from qf.research_config import (
    ResearchValidationError,
    validate_contract_request,
    validate_research_config,
)
from qf.research_live_view import LiveResearchView
from qf.research_results import RUN_ID, compare_runs, read_run, run_details, summarize_run
from qf.research_session import ResearchSession
from qf.window_host import run_window
from qf.workbench_store import WorkbenchStore

REASONS = {
    "connection_auth_or_data_failed": "连接、认证或目录数据未完成，请核对账号与权限后重新连接。",
    "connection_lost": "行情连接中断，当前显示最后收到的数据。",
    "main_contract_changed": "主力合约发生变化，正在重新核实图表。",
    "main_contract_capacity": "主力已换月，但订阅容量不足；保留旧合约图，请勿视为当前主力。",
    "unknown_selection": "所选品种不在当前市场目录中。",
    "catalog_loading": "行情服务已连接，正在读取品种目录。",
    "chart_data_unavailable": "当前合约K线未返回或读取失败，其他行情仍可查看。",
}
STATUSES = {"idle", "connecting", "ready", "waiting_data", "disconnected", "stopping",
            "stopped", "failed"}
LOAD_PHASES = {"idle", "connecting", "catalog", "bars", "chart", "ready", "failed", "stopped"}
ROW_FIELDS = ("continuous", "name", "exchange", "product", "underlying", "last_price",
              "change_percent", "volume", "open_interest", "quote_time", "data_state",
              "price_unit", "data_note")


def research_error(reason, *, code='research_request_failed', field_errors=None):
    return dict(ok=False, code=code, reason=reason, field_errors=field_errors or {})


def _history_summary(raw):
    if not isinstance(raw, dict):
        return None
    count = raw.get("valid_count")
    dates = {key: value if isinstance(value := raw.get(key), str)
             and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value) else None
             for key in ("first", "last")}
    years, issues = raw.get("years"), raw.get("issues")
    return {"valid_count": count if type(count) is int and count >= 0 else 0, **dates,
            "years": {key: value for key, value in years.items()
                      if isinstance(key, str) and re.fullmatch(r"\d{4}", key)
                      and type(value) is int and value > 0} if isinstance(years, dict) else {},
            "issues": [value for value in issues if isinstance(value, str)
                       and value in HISTORY_ISSUES] if isinstance(issues, list) else []}


class WorkbenchBridge:
    def __init__(self, root: Path, session: MarketSession, *, credential_store=None,
                 research_session=None):
        self._root, self._session = root, session
        self._lock = threading.RLock()
        self._store = WorkbenchStore(root / "data/workbench")
        cached = self._store.load()
        self._catalog, self._favorites = cached["catalog"], cached["favorites"]
        self._issue = cached["issue"]
        self._selected = None
        self._chart_mode = "actual"
        self._login = SavedLogin(root, store=credential_store)
        self._workspace_store = ChartWorkspaceStore(root / 'data/workbench')
        self._workspace_requests = None
        self._indicator_store = IndicatorStore(root / 'data/workbench')
        self._indicator_jobs = IndicatorJobs()
        self._experiments = ExperimentStore(root / 'data/workbench/experiments')
        self._research = research_session or ResearchSession(root / 'results')
        self._research_credentials = None
        self._replay = ReplayView(root / 'results')
        self._live_view = LiveResearchView(self._research.live_snapshot,
                                           state_provider=self._research.snapshot)
        self._live_job = None

    def list_research_runs(self):
        root = self._root / 'results'
        results = []
        for path in sorted(root.iterdir(), reverse=True) if root.exists() else []:
            if RUN_ID.fullmatch(path.name):
                try:
                    results.append(read_run(root, path.name))
                except ValueError:
                    results.append(dict(run_id=path.name, issue='旧版或损坏记录，无法按新实验复盘'))
        return dict(ok=True, runs=results)

    def get_research_result(self, run_id):
        try:
            return dict(ok=True, result=summarize_run(self._root/'results', run_id),
                        details=run_details(self._root/'results', run_id))
        except (ValueError, OSError):
            return dict(ok=False, reason='结果缺失、版本不支持或记录不完整，未使用当前行情补造。')

    def compare_research_runs(self, run_ids):
        try:
            return dict(ok=True, comparison=compare_runs(self._root/'results', run_ids))
        except (ValueError, OSError):
            return dict(ok=False, reason='请选择两个有效的新实验运行结果。')

    def get_research_fill(self, run_id, key):
        import sqlite3

        from qf.continuous_results import ContinuousReader
        from qf.research_results import run_path
        try:
            root = self._root/'results'
            if read_run(root, run_id)['config']['schema_version'] != 3:
                raise ValueError('仅连续实验使用分页成交查询')
            return dict(ok=True, details=ContinuousReader(run_path(root, run_id)).fill_details(key))
        except (ValueError, OSError, sqlite3.Error):
            return dict(ok=False, reason='该成交或关联证据不存在，未使用当前行情补造。')

    def get_research_trade(self, run_id, fill_key):
        import sqlite3

        from qf.research_protection import trade_explanation
        from qf.research_results import run_path
        try:
            root = self._root/'results'
            read_run(root, run_id)
            with sqlite3.connect(
                    (run_path(root, run_id)/'journal.sqlite3').as_uri()+'?mode=ro',
                    uri=True) as db:
                details = trade_explanation(db, fill_key=fill_key)
            return dict(ok=True, details=details)
        except (ValueError, OSError, sqlite3.Error):
            return dict(ok=False, reason='该成交或关联风险证据不存在。')

    def open_research_replay(self, run_id):
        with self._lock:
            try:
                url = self._replay.open(run_id)
                return dict(ok=True, url=url, run_id=run_id, revision=self._replay.revision)
            except (ValueError, OSError):
                return dict(ok=False, reason='无法打开复盘：请结束运行并核对保存的K线和结果。')

    def get_experiments(self):
        with self._lock:
            return {'ok': True, 'experiments': self._experiments.list()}

    def save_experiment(self, raw, experiment_id=None):
        with self._lock:
            try:
                config = validate_research_config(raw)
                if experiment_id is not None:
                    item = next(item for item in self._experiments.list()
                                if item['experiment_id'] == experiment_id and item.get('config'))
                    if (item['config'].get('contract_mode', 'fixed')
                            != getattr(config, 'contract_mode', 'fixed')):
                        return research_error('请复制为新实验后切换连续／固定合约模式。',
                            code='copy_mode_required',
                            field_errors={'contract_mode': '请先复制实验'})
                return dict(ok=True, experiment=self._experiments.save(
                    config, experiment_id=experiment_id), config=config.public())
            except ResearchValidationError as exc:
                return research_error('实验未保存：'+str(exc), code=exc.code,
                                      field_errors=exc.field_errors)
            except (ValueError, TypeError, KeyError, OSError):
                return research_error('实验未保存，请核对合约、周期和风险参数。')

    def copy_experiment(self, experiment_id, revision, name, upgrade_to_pivot=False):
        with self._lock:
            try:
                ref = self._experiments.copy(experiment_id, revision, name=name,
                                             upgrade_to_pivot=upgrade_to_pivot)
                return dict(ok=True, experiment=ref, config=self._experiments.load(
                    ref['experiment_id'], ref['revision']).public())
            except (ValueError, TypeError, KeyError, OSError):
                return dict(ok=False, reason='实验未复制，请先保存有效实验。')

    def copy_continuous_experiment(self, experiment_id, revision, name):
        with self._lock:
            try:
                ref = self._experiments.copy(experiment_id, revision, name=name,
                                             upgrade_to_continuous=True)
                return dict(ok=True, experiment=ref, config=self._experiments.load(
                    ref['experiment_id'], ref['revision']).public())
            except (ValueError, TypeError, KeyError, OSError):
                return dict(ok=False, reason='未能复制为主力连续实验，请核对原实验。')

    def _research_login(self):
        if self._research_credentials:
            return self._research_credentials
        return self._login.resolve(self._login.info()['user'], '')

    def get_research_contracts(self, continuous, start, end):
        with self._lock:
            try:
                request = validate_contract_request(continuous, start, end)
                if continuous not in {r['continuous'] for r in self._catalog}:
                    raise ResearchValidationError('continuous', '请先选择目录中的品种')
                return self._research.query_contracts(self._research_login(),
                    continuous=request['continuous'], start=date.fromisoformat(request['start']),
                    end=date.fromisoformat(request['end']))
            except ResearchValidationError as exc:
                return research_error('查询未开始：'+str(exc), code=exc.code,
                                      field_errors=exc.field_errors)
            except Exception:
                return research_error('查询未开始：请先连接行情或保存快期凭证；已有任务需结束。')

    def start_research(self, experiment_id, revision, mode, activate=False, resume=None,
                       fee_multiplier=1):
        with self._lock:
            try:
                config = self._experiments.load(experiment_id, revision)
                if config.strategy_version not in (2, 3):
                    return research_error('旧版实验只读，请复制为新版拐点实验后运行。',
                                          code='legacy_read_only')
                if config.schema_version == 3:
                    if mode != 'backtest':
                        return research_error('主力连续只用于历史回测；模拟请新建固定合约实验。',
                                              code='continuous_backtest_only')
                    return self._research.start(mode, config, self._research_login(),
                        activate=activate, resume=resume, fee_multiplier=fee_multiplier,
                        experiment_ref=dict(experiment_id=experiment_id, revision=revision))
                snapshot = self._research.snapshot()
                expected = dict(continuous=config.continuous,
                                start=str(config.start), end=str(config.end))
                if (snapshot.get('contract_request') != expected
                        or config.symbol not in {r['symbol'] for r in snapshot['contracts']}):
                    return research_error('未开始运行：请先查询并选择当前区间的实际合约。',
                        field_errors={'symbol': '点击“查询区间实际合约”，再选择月份'})
                row = next(r for r in snapshot['contracts'] if r['symbol'] == config.symbol)
                expiry = row.get('expire_datetime')
                if (mode == 'backtest' and type(expiry) in (int, float)
                        and math.isfinite(expiry) and expiry > 0):
                    expiry_day = datetime.fromtimestamp(expiry,
                        timezone(timedelta(hours=8))).date()
                    if config.end > expiry_day:
                        message = (f'回测未开始：{config.symbol} 到期日为 {expiry_day}，'
                                   f'结束日 {config.end} 已超出范围。'
                                   '请缩短结束日，再重新查询并选择实际合约。')
                        return research_error(message, code='contract_range_exceeds_expiry',
                            field_errors={'end': f'请设置为 {expiry_day} 或更早的日期',
                                          'symbol': '该月份合约不能覆盖当前结束日'})
                return self._research.start(mode, config, self._research_login(), activate=activate,
                    resume=resume, fee_multiplier=fee_multiplier,
                    experiment_ref=dict(experiment_id=experiment_id, revision=revision))
            except Exception:
                return research_error('未开始运行：请核对合约、参数和凭证；已有任务需先停止。')

    def stop_research(self, flatten=False):
        try:
            self._research.stop(flatten=flatten)
            return dict(ok=True, reason='正在平仓并停止，请核对成交。' if flatten
                        else '正在停止任务；停止不代表平仓。')
        except ValueError:
            return dict(ok=False, reason='当前实验不可执行此停止操作。')

    def get_research_state(self):
        return self._research.snapshot()

    def get_research_live_snapshot(self):
        return self._research.live_snapshot()

    def open_research_live_chart(self):
        with self._lock:
            try:
                state = self._research.snapshot()
                if (not self._research.live_snapshot() and not state.get('running')
                        and state.get('status') in ('failed', 'frozen', 'stopped',
                                                   'backtest_finished')):
                    return research_error('本次任务已结束，未产生可显示的K线。'
                                          '请先处理上方失败原因，再运行回测。')
                if not state.get('job_id') and not self._research.live_snapshot():
                    return research_error('请先运行一个回测或模拟实验，再观看交易过程。')
                if state.get('job_id') != self._live_job:
                    self._live_view.close()
                    self._live_job = state.get('job_id')
                url = self._live_view.open()
                return dict(ok=True, url=url, run_id=self._live_view.run_id,
                            generation=self._live_view.generation)
            except (ValueError, OSError):
                return research_error('运行图未能打开；后台计算继续，请查看进度。')

    def exit_message(self):
        state = self._research.snapshot()
        if state.get('running'):
            return ('确定退出天勤策略工作台吗？研究任务将停止，持仓不会自动平仓；'
                    '退出后本地止损保护不再运行，未确认的委托会保留为待核实状态。')
        return '确定退出天勤策略工作台吗？'

    def get_indicators(self):
        with self._lock:
            return {**self._indicator_store.load(), 'catalog': indicator_catalog(),
                    'defaults': default_indicators()}

    def save_indicators(self, config):
        with self._lock:
            try:
                self._indicator_store.save(config)
                return {'ok': True, 'reason': '指标设置已保存。'}
            except (ValueError, TypeError, OSError):
                return {'ok': False, 'reason': '指标设置未保存，原文件已保留。'}

    def submit_indicator_calculation(self, request):
        if not isinstance(request, dict):
            return {'ok': False, 'reason': '指标请求无效。'}
        state = self.get_state()
        pane = next((p for p in state.get('panes', [])
                     if p['id'] == request.get('pane_id')), None)
        if (not pane or state.get('generation') != request.get('generation')
                or pane.get('revision') != request.get('chart_revision')
                or pane.get('symbol') != request.get('symbol')
                or period_for(pane) != request.get('period')):
            return {'ok': False, 'reason': '指标目标已变化，请等待当前图表就绪。'}
        return self._indicator_jobs.submit(request)

    def poll_indicator_calculations(self, job_ids):
        return self._indicator_jobs.poll(job_ids)

    def get_workspace(self):
        with self._lock:
            return self._workspace_store.load()

    def save_workspace(self, workspace):
        with self._lock:
            try:
                self._workspace_store.save(workspace)
                return {'ok': True, 'reason': '布局已保存。'}
            except (OSError, ValueError, TypeError):
                return {'ok': False, 'reason': '布局未保存；原文件已保留，请检查本机布局文件。'}

    def set_workspace(self, symbols, panes):
        with self._lock:
            try:
                requests = validate_panes(panes, requests=True)
                known = {r['continuous'] for r in self._catalog}
                if (not isinstance(symbols, list) or len(symbols) > 100
                        or any(not isinstance(s, str) or s not in known for s in symbols)
                        or any(p['continuous'] is not None and p['continuous'] not in known
                               for p in requests)):
                    raise ValueError('unknown selection')
                favorites = [s for s in self._favorites if s in known]
                self._session.set_workspace(list(dict.fromkeys([*symbols, *favorites])), requests)
                self._workspace_requests = {p['id']: p for p in requests}
                first = next((p for p in requests if p['id'] == 'pane-1'), {})
                self._selected = first.get('continuous')
                self._chart_mode = first.get('mode', 'actual')
                return {'ok': True, 'reason': ''}
            except (ValueError, TypeError):
                return {'ok': False,
                        'reason': '图表设置未应用：品种无效或订阅已达上限，请减少需求或重新连接。'}

    def _public_panes(self, raw, rows):
        output = []
        mappings = {r.get('continuous'): r.get('underlying') for r in rows}
        for value in raw if isinstance(raw, list) else []:
            if not isinstance(value, dict):
                continue
            try:
                request = validate_panes([{k: value.get(k) for k in
                    ('id', 'continuous', 'mode', 'period', 'revision')}], requests=True)[0]
            except (ValueError, TypeError):
                continue
            if (self._workspace_requests is not None
                    and self._workspace_requests.get(request['id']) != request):
                continue
            expected = (request['continuous'] if request['mode'] == 'continuous' else
                        mappings.get(request['continuous']))
            symbol = value.get('symbol')
            stale = (value.get('mapping_stale') is True and request['mode'] == 'actual'
                     and value.get('reason') == 'main_contract_capacity'
                     and value.get('mapped_symbol') == expected and isinstance(expected, str)
                     and isinstance(symbol, str) and symbol != expected
                     and isinstance(request['continuous'], str)
                     and re.fullmatch(re.escape(request['continuous'][5:]) + r'\d{3,4}',
                                      symbol) is not None)
            if symbol is not None and symbol != expected and not stale:
                continue
            duration = PERIODS[period_for(request)] * 1_000_000_000
            if value.get('duration') != duration:
                continue
            output.append({**request, 'symbol': symbol, 'duration': duration,
                           'mapping_stale': stale, 'mapped_symbol': expected if stale else None,
                           'history': _history_summary(value.get('history')),
                           'status': value.get('status') if value.get('status') in
                           ('idle', 'loading', 'ready', 'unavailable') else 'unavailable',
                           'reason': REASONS.get(value.get('reason'),
                               '订阅容量已达上限，请减少需求或重新连接。' if
                               value.get('reason') == 'subscription_limit' else '')})
        return output

    def get_login_state(self):
        with self._lock:
            return self._login.info()

    def forget_login(self):
        with self._lock:
            try:
                self._login.forget()
                return {"ok": True, "reason": "已忘记账号密码；当前连接不受影响。"}
            except ValueError:
                return {"ok": False, "reason": "忘记账号密码未完成，请稍后重试。"}

    def login(self, user, password, remember=True):
        with self._lock:
            try:
                if self._session.running:
                    raise ValueError("already running")
                credentials = self._login.resolve(user, password)
                self._login.prepare(*credentials, remember)
                self._session.start(*credentials)
                self._research_credentials = credentials
                self._selected = None
                self._chart_mode = "actual"
                self._workspace_requests = None
                return {"ok": True, "reason": "正在连接行情，请稍候。"}
            except Exception:
                self._login.discard()
                return {"ok": False,
                        "reason": "未开始连接，请填写或使用已保存的凭证，并确认行情已停止。"}

    def get_state(self):
        with self._lock:
            raw = self._session.snapshot()
            catalog = catalog_rows(raw.get("catalog", []))
            if catalog and catalog != self._catalog:
                self._catalog = catalog
                self._save()
            status = raw.get("status") if raw.get("status") in STATUSES else "failed"
            if status in ("ready", "waiting_data"):
                self._login.confirm()
            elif status in ("failed", "stopped"):
                self._login.discard()
            if self._selected is None:
                self._selected = raw.get("selected")
            address = raw.get("chart_url")
            matching = (raw.get("selected") == self._selected
                        and raw.get("chart_mode", "actual") == self._chart_mode)
            address = address if (matching or self._workspace_requests is not None) and \
                allowed_chart_url(address) else None
            rows = [{k: row.get(k) for k in ROW_FIELDS} for row in raw.get("rows", [])]
            heartbeat = raw.get("heartbeat_seconds", 0)
            display_catalog = [{**row, "price_unit": price_unit(row["exchange"], row["product"])}
                               for row in self._catalog]
            connected = raw.get("connected")
            connected = (connected if type(connected) is bool else
                         None if status in ("connecting", "stopping") else
                         status in ("ready", "waiting_data"))
            chart_status = raw.get("chart_status")
            loading = raw.get("loading", {})
            loading = loading if isinstance(loading, dict) else {}
            phase = loading.get("phase")
            progress = {"phase": phase if isinstance(phase, str) and phase in LOAD_PHASES
                        else "idle"}
            for field in ("done", "total", "elapsed_seconds"):
                value = loading.get(field)
                progress[field] = value if type(value) is int and value >= 0 else None
            chart_symbol = raw.get("chart_symbol")
            if not isinstance(chart_symbol, str) or (chart_symbol != self._selected
                    and chart_symbol not in {row.get("underlying") for row in rows}):
                chart_symbol = None
            revision = raw.get("chart_revision")
            generation = raw.get('generation', 0)
            return {"status": status, "catalog": display_catalog, "rows": rows,
                    'generation': generation if type(generation) is int and generation >= 0 else 0,
                    'panes': self._public_panes(raw.get('panes'), rows),
                    'account': public_account(raw.get('account')),
                    "loading": progress, "chart_mode": self._chart_mode,
                    "chart_symbol": chart_symbol,
                    "chart_revision": revision if matching and type(revision) is int
                    and revision > 0 else 0,
                    "history": _history_summary(raw.get("history")) if matching else None,
                    "connected": connected,
                    "chart_status": chart_status if chart_status in
                    {"idle", "loading", "ready", "unavailable"} else "idle",
                    "selected": self._selected, "chart_url": address,
                    "reason": REASONS.get(raw.get("reason"), ""),
                    "heartbeat_seconds": heartbeat if type(heartbeat) is int else 0,
                    "favorites": list(self._favorites),
                    "issue": self._issue or self._login.info()["issue"],
                    "cache_state": "live" if catalog and status in ("ready", "waiting_data")
                    else "cached" if self._catalog else "empty"}

    def set_view(self, symbols, selected, chart_mode="actual"):
        with self._lock:
            known = {r["continuous"] for r in self._catalog}
            if (not isinstance(symbols, list) or len(symbols) > 98
                    or chart_mode not in ("actual", "continuous")
                    or not all(isinstance(s, str) and s in known for s in symbols)
                    or selected is not None and
                    (not isinstance(selected, str) or selected not in known)):
                return {"ok": False, "reason": "所选品种不可用或超过订阅上限。"}
            try:
                favorites = [s for s in self._favorites if s in known]
                self._session.set_view(list(dict.fromkeys([*symbols, *favorites])), selected,
                                       chart_mode)
                self._selected = selected
                self._chart_mode = chart_mode
                return {"ok": True, "reason": ""}
            except ValueError:
                return {"ok": False, "reason": "当前行情订阅已达到上限，请减少自选。"}

    def set_favorites(self, symbols):
        with self._lock:
            known = {r["continuous"] for r in self._catalog}
            if (not isinstance(symbols, list) or len(symbols) > 50
                    or not all(isinstance(s, str) and s in known for s in symbols)):
                return {"ok": False, "reason": "自选需来自市场目录，最多 50 项。"}
            before = self._favorites
            self._favorites = list(dict.fromkeys(symbols))
            if not self._save():
                self._favorites = before
                return {"ok": False, "reason": self._issue}
            return {"ok": True, "reason": "自选已保存。"}

    def _save(self):
        try:
            self._store.save(self._catalog, self._favorites)
            return True
        except (OSError, ValueError):
            self._issue = "本机目录或自选无法保存，原文件已保留；请检查 data/workbench。"
            return False

    def open_resource(self, key):
        urls = {"docs": "https://doc.shinnytech.com/tqsdk/latest/usage/web_gui.html",
                "jin10": "https://open.jin10.com/",
                "calendar": "https://rili.jin10.com/"}
        try:
            if key == "legacy":
                subprocess.Popen(
                    [str(self._root / ".venv-tqsdk/Scripts/pythonw.exe"), "-I", "-X", "utf8",
                     "-B", str(self._root / "tools/gui_entry.py")], cwd=self._root,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif isinstance(key, str) and key in urls:
                webbrowser.open(urls[key])
            else:
                return {"ok": False, "reason": "该入口不可用。"}
            return {"ok": True, "reason": "已打开。"}
        except (OSError, ValueError, TypeError):
            return {"ok": False, "reason": "无法打开入口，请核对本机环境。"}

    def disconnect(self):
        with self._lock:
            self._login.discard()
        self._session.stop()
        return {"ok": True, "reason": "正在断开行情连接。"}

    def _request_close(self):
        self._indicator_jobs.close()
        self._session.stop()
        research_closed = self._research.close()
        try:
            self._replay.close()
            self._live_view.close()
        except ValueError:
            return False
        if research_closed and not self._session.running:
            self._research_credentials = None
            return True
        return False


def main():
    root = Path(__file__).resolve().parent.parent
    bridge = WorkbenchBridge(root, MarketSession())
    run_window(root / "qf/web/index.html", bridge, bridge._request_close)
