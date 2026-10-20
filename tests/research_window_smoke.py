"""完整只读观察窗真实 WebView2 验收；不连接账户。"""

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402

from qf.research_window import ResearchWindowView  # noqa: E402

JOB_ID = 'a'*32
LEDGER = {
    'available': True, 'reconciled': True, 'truncated': False,
    'fee_total': '30.42', 'fee_reconciled_difference': '0', 'reason': '',
    'trades': [dict(
        trade_id='trade-1', status='closed', direction=1,
        first_symbol='SHFE.rb2505', last_symbol='SHFE.rb2505', quantity=5,
        entry_time_ns='1735780439000000000', entry_price='3301',
        exit_time_ns='1735782539000000000', exit_price='3315',
        initial_stop='3284', final_stop='3302', exit_reason='ma_reverse',
        fee='30.42', gross_pnl='700', net_pnl='669.58', fill_count=2)],
    'fills': [dict(
        key='fill-open', trade_id='trade-1', symbol='SHFE.rb2505',
        direction='BUY', offset='OPEN', role='strategy_open', volume=5,
        price='3301', time_ns='1735780439000000000', fee='15.21',
        trade_status='closed', entry_price='3301', exit_price='3315',
        initial_stop='3284', final_stop='3302', trade_net_pnl='669.58',
        exit_reason='ma_reverse')],
}
STATE = {
    'job_id': JOB_ID, 'status': 'active', 'running': True,
    'run_id': '20261020T000000-abcdef123456',
    'config': {'name': '观察窗验收', 'symbol': 'SHFE.rb2505', 'bar_seconds': 60},
    'progress': {'percent': 37, 'completed_bars': 120, 'fill_count': 2},
    'account': {
        'kind': 'backtest', 'time_ns': '1730700000000000000', 'status': 'active',
        'summary': {'balance': '101000', 'float_profit': '670', 'margin': '3000',
                    'available': '98000', 'commission': '30.42',
                    'commission_total': '30.42', 'roll_commission': '0',
                    'actual_fill_count': 2, 'closed_trade_count': 1, 'open_position': 0},
        'positions': [], 'orders': [], 'trades': [],
        'truncated': {'positions': False, 'orders': False, 'trades': False},
        'availability': {'summary': 'recorded', 'positions': 'recorded',
                         'orders': 'recorded', 'trades': 'recorded'},
    },
    'risk': {'side': 0, 'quantity': 0},
}


class Harness:
    def __init__(self):
        self.window = None
        self.result = None
        self.original_create_window = webview.create_window

    def create_window(self, *args, **kwargs):
        kwargs.update(width=1200, height=900, hidden=True)
        self.window = self.original_create_window(*args, **kwargs)
        self.window.create_confirmation_dialog = lambda *a, **k: True
        self.window.events.loaded += self.exercise
        return self.window

    def exercise(self):
        def run():
            try:
                script = Path(__file__).with_name('research_window_browser.js').read_text(
                    encoding='utf-8')
                self.window.evaluate_js(script)
                end = time.monotonic()+25
                while time.monotonic()<end:
                    value = self.window.evaluate_js('window.__researchWindowProbe||null')
                    if value and (value.get('done') or value.get('error')):
                        self.result = value
                        break
                    time.sleep(.1)
                if self.result is None:
                    self.result = {'error': '观察窗流程超时',
                                   'stage': self.window.evaluate_js(
                                       'window.__researchStage||null')}
            except Exception as exc:
                self.result = {'error': type(exc).__name__+': '+str(exc)}
            finally:
                self.window.destroy()
        threading.Thread(target=run, daemon=True).start()

    def start(self, **kwargs):
        webview.start(**kwargs)


def main():
    view = ResearchWindowView(
        JOB_ID, lambda: STATE, lambda: LEDGER, lambda: 'http://127.0.0.1:9')
    url = view.open()
    harness = Harness()
    try:
        webview.create_window = harness.create_window
        webview.create_window('研究观察窗验收', url)
        harness.start(gui='edgechromium', debug=False, private_mode=True)
    finally:
        view.close()
    print('RESEARCH_WINDOW_RESULT='+json.dumps(harness.result, ensure_ascii=False))
    if not harness.result or not harness.result.get('done'):
        raise SystemExit(1)
    print('RESEARCH_WINDOW_OK')


if __name__ == '__main__':
    main()
