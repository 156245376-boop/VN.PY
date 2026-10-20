"""任务板图形联调：使用内存任务，不启动账户或真实SDK。"""

import copy
import json
import sys
import tempfile
import threading
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding='utf-8')

import webview  # noqa: E402
from research_workbench_smoke import MarketFixture  # noqa: E402
from test_credentials import MemoryStore  # noqa: E402

from qf.window_host import run_window  # noqa: E402
from qf.workbench import WorkbenchBridge  # noqa: E402


class MemoryJobs:
    def __init__(self):
        self.capacity = 1
        self.items = []
        self.submits = 0
        self.removed = []

    def submit(self, config, *, credentials, experiment_ref=None,
               include_fee_stress=False, request_id=None):
        self.submits += 1
        job_id = f'{self.submits:032x}'
        running = self.submits <= self.capacity
        self.items.append(dict(
            job_id=job_id, epoch=uuid.uuid4().hex, run_id='fixture-run-'+job_id[:8],
            status='active' if running else 'waiting', running=running,
            config=config.public(), experiment_ref=experiment_ref or {},
            fee_multiplier=1, parent_job_id=None, watch=False,
            progress=dict(stage='backtesting', percent=37, completed_bars=120,
                          fill_count=2, elapsed_seconds=12, last_advance_age_seconds=0,
                          current_ns='1730700000000000000') if running else None,
            account=dict(
                kind='backtest', time_ns='1730700000000000000', status='active',
                summary=dict(balance='101000', float_profit='700', margin='3000',
                             available='98000', commission='30.42',
                             commission_total='30.42', roll_commission='0',
                             actual_fill_count=2, closed_trade_count=1,
                             open_position=0),
                positions=[dict(symbol='SHFE.rb2505', pos_long=0, pos_short=0,
                                float_profit=0, margin=0)],
                orders=[dict(symbol='SHFE.rb2505', direction='BUY', offset='OPEN',
                             volume_orign=5, volume_left=0, limit_price='3301',
                             status='FINISHED')],
                trades=[dict(symbol='SHFE.rb2505', direction='BUY', offset='OPEN',
                             volume=5, price=3301, trade_date_time=1735780439000000000)],
                availability=dict(summary='recorded', positions='recorded',
                                  orders='recorded', trades='recorded'),
                truncated=dict(positions=False, orders=False, trades=False),
            ) if running else None,
            risk=dict(side=1, quantity=1, initial_r='1000', stop_price='3284',
                      stage=1) if running else {},
            reason=None if running else 'capacity'))
        return dict(job_ids=[job_id], selected_job_id=job_id)

    def submit_many(self, configs, *, credentials, experiment_refs,
                    include_fee_stress, request_id=None):
        groups, ids = [], []
        for config, ref in zip(configs, experiment_refs, strict=True):
            result = self.submit(
                config, credentials=credentials, experiment_ref=ref,
                include_fee_stress=False, request_id=None)
            groups.append(result['job_ids'])
            ids.extend(result['job_ids'])
        return dict(job_ids=ids, groups=groups, selected_job_id=ids[0])

    def _get(self, job_id):
        return next(job for job in self.items if job['job_id'] == job_id)

    def list(self):
        return [copy.deepcopy(job) for job in self.items]

    def snapshot(self, job_id):
        return copy.deepcopy(self._get(job_id))

    def stop(self, job_id):
        job = self._get(job_id)
        job.update(status='stopped', running=False, reason='requested_stop')
        waiting = next((item for item in self.items if item['status'] == 'waiting'), None)
        if waiting is not None:
            waiting.update(status='active', running=True, reason=None,
                           progress=copy.deepcopy(job['progress']),
                           account=copy.deepcopy(job['account']),
                           risk=copy.deepcopy(job['risk']))

    def remove(self, job_id):
        job = self._get(job_id)
        if job['running']:
            raise ValueError()
        self.removed.append(job_id)
        self.items.remove(job)

    def set_watch(self, job_id, enabled):
        self._get(job_id)['watch'] = bool(enabled)

    def live_snapshot(self, job_id):
        return None

    def set_capacity(self, value):
        self.capacity = value

    def close(self):
        return True


class Replay:
    revision = 'fixture'

    def open(self, run_id):
        return 'http://127.0.0.1:9/'+run_id


TRADE_LEDGER = dict(
    available=True, reconciled=True, truncated=False, fee_total='30.42',
    fee_reconciled_difference='0', total=1,
    trades=[dict(
        trade_id='trade-1', status='closed', direction=1, first_symbol='SHFE.rb2505',
        last_symbol='SHFE.rb2505', quantity=5, entry_time_ns='1735780439000000000',
        entry_price='3301', exit_time_ns='1735782539000000000', exit_price='3315',
        initial_stop='3284', final_stop='3302', exit_reason='ma_reverse',
        fee='30.42', gross_pnl='700', net_pnl='669.58', fill_count=2,
        fills=[
            dict(key='fill-open', trade_id='trade-1', symbol='SHFE.rb2505',
                 direction='BUY', offset='OPEN', role='strategy_open', volume=5,
                 price='3301', time_ns='1735780439000000000', fee='15.21',
                 trade_status='closed', entry_price='3301', exit_price='3315',
                 initial_stop='3284', final_stop='3302', trade_net_pnl='669.58',
                 exit_reason='ma_reverse'),
            dict(key='fill-close', trade_id='trade-1', symbol='SHFE.rb2505',
                 direction='SELL', offset='CLOSETODAY', role='strategy_close', volume=5,
                 price='3315', time_ns='1735782539000000000', fee='15.21',
                 trade_status='closed', entry_price='3301', exit_price='3315',
                 initial_stop='3284', final_stop='3302', trade_net_pnl='669.58',
                 exit_reason='ma_reverse')]),
    ],
    fills=[],
)
TRADE_LEDGER['fills'] = TRADE_LEDGER['trades'][0]['fills']


class Harness:
    def __init__(self):
        self.window = None
        self.result = None

    def create_window(self, *args, **kwargs):
        kwargs.update(width=960, height=680)
        self.window = webview.create_window(*args, **kwargs)
        self.window.create_confirmation_dialog = lambda *a, **k: True
        return self.window

    def start(self, **kwargs):
        def exercise():
            try:
                script = Path(__file__).with_name('research_jobs_browser.js').read_text(
                    encoding='utf-8')
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    if self.window.evaluate_js(
                            "!!window.pywebview?.api && "
                            "!!document.querySelector('[data-field=continuous]')?.options.length"):
                        break
                    time.sleep(.1)
                self.window.evaluate_js(script)
                deadline = time.monotonic()+30
                while time.monotonic() < deadline:
                    value = self.window.evaluate_js('window.__researchJobsSmoke||null')
                    if value and (value.get('done') or value.get('error')):
                        self.result = value
                        break
                    time.sleep(.1)
                if not self.result:
                    self.result = dict(error='超时', stage=self.window.evaluate_js(
                        'window.__researchJobsStage||null'))
            except Exception as exc:
                self.result = dict(error=type(exc).__name__+': '+str(exc))
            finally:
                self.window.destroy()
        threading.Thread(target=exercise, daemon=True).start()
        webview.start(**kwargs)


def main():
    location = nullcontext(sys.argv[1]) if len(sys.argv) > 1 else tempfile.TemporaryDirectory()
    with location as directory:
        root = Path(directory)
        store = MemoryStore()
        store.save('fixture-user', 'fixture-password')

        class FixtureBridge(WorkbenchBridge):
            def get_backtest_trade_ledger(self, job_id):
                return dict(ok=True, ledger=TRADE_LEDGER)

        bridge = FixtureBridge(root, MarketFixture(), credential_store=store)
        jobs = MemoryJobs()
        bridge._jobs_bridge._jobs = jobs
        bridge._jobs_bridge.replay = Replay()
        harness = Harness()
        run_window(Path(__file__).resolve().parents[1]/'qf/web/index.html', bridge,
                   bridge._request_close, webview_module=harness)
        print('RESEARCH_JOBS_WORKBENCH_RESULT='+
              json.dumps(harness.result, ensure_ascii=False))
        if not harness.result or not harness.result.get('done'):
            raise SystemExit(1)
        assert jobs.submits == 3
        assert jobs.capacity == 1
        assert jobs.removed == ['0'*31+'2']
        assert jobs.items[0]['status'] == 'stopped'
        assert next(job for job in jobs.items
                    if job['job_id'] == harness.result['stopCJob'])['status'] == 'stopped'
        print('RESEARCH_JOBS_WORKBENCH_OK')


if __name__ == '__main__':
    main()
