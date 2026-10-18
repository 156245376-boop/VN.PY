"""SDK网络/撮合边界替身；信号、风控、Guard、事务均使用真实产品代码。"""

from types import SimpleNamespace as NS

import pandas as pd

BASE = int(pd.Timestamp('2025-03-03 09:00:00', tz='Asia/Shanghai').value)


class Finished(Exception):
    pass


class Sim:
    def __init__(self, init_balance=100000):
        self.fee = 2
        self.tqsdk_stat = {'end_balance': init_balance, 'commission': 0}

    def get_margin(self, symbol):
        return 3000

    def get_commission(self, symbol):
        return self.fee

    def set_commission(self, symbol, fee):
        self.fee = fee


class Api:
    instances = []
    scenario = 'normal'

    def __init__(self, **kwargs):
        self.kwargs, self.steps, self.closed = kwargs, 0, False
        self._data = {'notify': {}}
        self.positions, self.orders, self.trades, self.subscriptions = {}, {}, {}, []
        self.targets, self.cancels = [], 0
        self.account = NS(balance=100000., available=100000., commission=0.)
        self.quote = NS(underlying_symbol='SHFE.rb2505', datetime='2025-03-03 09:05:00.000000',
                        last_price=1000., price_tick=1., volume_multiple=10., margin=3000.,
                        commission=2., open_min_limit_order_volume=1,
                        open_min_market_order_volume=1,
                        expired=False, expire_datetime=4102444800.)
        self.serial = pd.DataFrame([dict(id=i, datetime=BASE+i*60_000_000_000,
            open=v, high=v, low=v, close=v, volume=10, close_oi=20)
            for i, v in enumerate([3., 2., 1., 2., 3., 999.])])
        self.instances.append(self)
        if self.scenario == 'expired':
            self.quote.expired = True
        if self.scenario == 'empty':
            self.serial['id'] = [-6, -5, -4, -3, -2, -1]
            self.serial['datetime'] = 0
            for key in ('open', 'high', 'low', 'close'):
                self.serial[key] = float('nan')

    def get_quote(self, symbol):
        return self.quote

    def get_kline_serial(self, symbol, duration, **kwargs):
        self.subscriptions.append(('kline', duration))
        return self.serial

    def get_tick_serial(self, symbol, **kwargs):
        self.subscriptions.append(('tick', symbol))
        if self.scenario == 'tick_denied':
            raise RuntimeError('private-secret')
        return pd.DataFrame([dict(datetime=BASE+300_000_000_000, last_price=1000)])

    def get_account(self):
        return self.account

    def get_position(self):
        return self.positions

    def get_order(self):
        return self.orders

    def get_trade(self):
        return self.trades

    def insert_order(self, symbol, direction, offset, volume, **kwargs):
        oid = f'o{len(self.orders)}'
        item = NS(order_id=oid, symbol=symbol, direction=direction, offset=offset,
                  volume_left=volume, status='ALIVE', is_error=self.scenario == 'reject')
        self.orders[oid] = item
        return item

    def wait_update(self, **kwargs):
        self.steps += 1
        for order in list(self.orders.values()):
            if order.status == 'FINISHED':
                continue
            quantity = order.volume_left
            if self.scenario == 'partial' and order.offset == 'OPEN':
                if quantity == 3:
                    quantity = 2
                elif not self.cancels:
                    continue
            if self.scenario == 'stuck':
                continue
            key = f't{len(self.trades)}'
            self.trades[key] = NS(trade_id=key, order_id=order.order_id,
                exchange_id='SHFE', instrument_id='rb2505', direction=order.direction,
                offset=order.offset, volume=quantity, price=self.quote.last_price,
                trade_date_time=BASE+300_000_000_000+self.steps*1_000_000_000)
            pos = self.positions.setdefault(order.symbol, NS(pos_long=0, pos_short=0))
            if order.offset == 'OPEN':
                if order.direction == 'BUY':
                    pos.pos_long += quantity
                else:
                    pos.pos_short += quantity
            elif order.direction == 'SELL':
                pos.pos_long -= quantity
            else:
                pos.pos_short -= quantity
            order.volume_left -= quantity
            if not order.volume_left:
                order.status = 'FINISHED'
            self.account.commission += quantity*2
        prices = [1050, 1100, 1025, 1025, 1025, 1025]
        if self.scenario == 'reverse':
            prices = [1000]*6
            if self.steps == 1:
                self.serial['datetime'] += 60_000_000_000
                self.serial['close'] = [1., 2., 3., 2., 1., 999.]
                self.quote.datetime = '2025-03-03 09:06:01.000000'
        if self.scenario == 'partial':
            prices = [1050, 1001, 1001, 1001, 1001, 1001]
        self.quote.last_price = prices[min(self.steps-1, len(prices)-1)]
        minute = '06' if self.scenario == 'reverse' else '05'
        self.quote.datetime = f'2025-03-03 09:{minute}:{self.steps:02d}.000000'
        if self.scenario == 'disconnect':
            self._data['notify']['n1'] = {'code': 2019112911}
        if self.scenario == 'foreign':
            self.orders['foreign'] = NS(status='ALIVE', is_error=False)
        if self.steps >= 6:
            self.kwargs['account'].tqsdk_stat = {
                'end_balance': self.account.balance, 'commission': self.account.commission}
            raise Finished()
        return True

    def close(self):
        self.closed = True

    def _print(self, *args, **kwargs):
        pass


class Target:
    def __init__(self, api, symbol, **kwargs):
        self.api, self.symbol, self.cancelled = api, symbol, False
        self.options = kwargs

    def set_target_volume(self, target):
        self.api.targets.append(target)
        pos = self.api.positions.get(self.symbol, NS(pos_long=0, pos_short=0))
        actual = pos.pos_long-pos.pos_short
        if target != actual:
            self.api.insert_order(self.symbol, 'BUY' if target > actual else 'SELL',
                                  offset='CLOSE' if actual else 'OPEN', volume=abs(target-actual))

    def cancel(self):
        self.cancelled = True
        self.api.cancels += 1

    def is_finished(self):
        return self.cancelled and all(o.status == 'FINISHED' for o in self.api.orders.values())


def sdk_for(scenario='normal'):
    Api.instances = []
    Api.scenario = scenario
    return NS(TqApi=Api, TqSim=Sim, TqKq=lambda: Sim(), TqAuth=lambda *a: object(),
              TqBacktest=lambda **kw: NS(_start_dt=BASE-86400000000000,
                                        _end_dt=BASE+5*86400000000000),
              TargetPosTask=Target, BacktestFinished=Finished)
