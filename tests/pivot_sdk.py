"""有真实拐点／交叉输入的网络边界替身；不替换产品策略计算。"""

import time
from types import SimpleNamespace as NS

import pandas as pd
from research_sdk import BASE, Api, Finished, Sim, sdk_for


class PivotApi(Api):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        values = [1000.] * 34 + [999., 999., 995., 999., 999., 1010., 1000.]
        self.serial = pd.DataFrame([dict(id=i, datetime=BASE+(i-35)*60_000_000_000,
            open=v, high=v, low=v, close=v, volume=10, close_oi=20)
            for i, v in enumerate(values)])
        self.live = 'backtest' not in kwargs
        self.quote.ask_price1, self.quote.bid_price1 = 1001., 999.
        self.quote.price_decs = 0
        self.quote.instrument_name = '螺纹钢测试合约'

    def get_kline_serial(self, symbol, duration, **kwargs):
        self.subscriptions.append(('kline', duration))
        if duration != 60:
            count = len(self.serial)
            self.serial['datetime'] = [BASE+300_000_000_000-(count-1-i)*duration*1_000_000_000
                                       for i in range(count)]
        return self.serial

    def get_trading_calendar(self, start, end):
        if self.scenario == 'calendar_missing':
            raise ValueError('private-service-response')
        dates = pd.date_range(start, end)
        return pd.DataFrame(dict(date=dates, trading=[d.weekday() < 5 for d in dates]))

    def insert_order(self, *args, **kwargs):
        order = super().insert_order(*args, **kwargs)
        if self.scenario == 'reject':
            order.status = 'FINISHED'
        return order

    def wait_update(self, **kwargs):
        if self.live:
            time.sleep(.02)
            self.steps += 1
            self.quote.datetime = (pd.Timestamp('2025-03-03 09:05:00')
                + pd.Timedelta(seconds=self.steps)).strftime('%Y-%m-%d %H:%M:%S.%f')
            return True
        try:
            before_fee = self.account.commission
            result = super().wait_update(**kwargs)
        except Finished:
            self.kwargs['backtest']._current_dt = 2145888000000000000
            raise
        fee = self.kwargs['account'].get_commission('SHFE.rb2505')
        self.account.commission = before_fee+(self.account.commission-before_fee)*fee/2
        prices = [1005., 1010., 1002., 1002., 1002.]
        if self.scenario == 'partial':
            prices = [1005., 1000., 1000., 1000., 1000.]
        if self.scenario == 'beyond_stop':
            prices = [994.] * 5
        self.quote.last_price = prices[min(self.steps-1, 4)]
        self.quote.ask_price1 = self.quote.last_price+1
        self.quote.bid_price1 = self.quote.last_price-1
        row = self.serial.index[-1]
        self.serial.loc[row, 'close'] = self.quote.last_price
        self.serial.loc[row, 'high'] = max(self.serial.loc[row, 'high'], self.quote.last_price)
        self.serial.loc[row, 'low'] = min(self.serial.loc[row, 'low'], self.quote.last_price)
        self.kwargs['backtest']._current_dt = BASE+300_000_000_000+self.steps*1_000_000_000
        return result


def sdk_for_pivot(scenario='normal'):
    sdk = sdk_for(scenario)
    sdk.TqApi = PivotApi
    sdk.TqSim = Sim
    sdk.TqBacktest = lambda **kw: NS(_start_dt=BASE, _end_dt=BASE+306_000_000_000,
                                     _current_dt=BASE+300_000_000_000)
    return sdk
