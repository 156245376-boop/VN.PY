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
        running = self.submits == 1
        self.items.append(dict(
            job_id=job_id, epoch=uuid.uuid4().hex, run_id='fixture-run-'+job_id[:8],
            status='active' if running else 'waiting', running=running,
            config=config.public(), experiment_ref=experiment_ref or {},
            fee_multiplier=1, parent_job_id=None, watch=False,
            progress=dict(stage='backtesting', percent=37, completed_bars=120,
                          fill_count=2, elapsed_seconds=12, last_advance_age_seconds=0,
                          current_ns='1730700000000000000') if running else None,
            account=dict(equity='101000', commission='20') if running else None,
            risk=dict(side=1, quantity=1, initial_r='1000', stop_price='3284',
                      stage=1) if running else {},
            reason=None if running else 'capacity'))
        return dict(job_ids=[job_id], selected_job_id=job_id)

    def _get(self, job_id):
        return next(job for job in self.items if job['job_id'] == job_id)

    def list(self):
        return [copy.deepcopy(job) for job in self.items]

    def snapshot(self, job_id):
        return copy.deepcopy(self._get(job_id))

    def stop(self, job_id):
        job = self._get(job_id)
        job.update(status='stopped', running=False, reason='requested_stop')

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
        bridge = WorkbenchBridge(root, MarketFixture(), credential_store=store)
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
        assert jobs.submits == 2
        assert jobs.removed == ['0'*31+'2']
        assert jobs.items[0]['status'] == 'stopped'
        print('RESEARCH_JOBS_WORKBENCH_OK')


if __name__ == '__main__':
    main()
