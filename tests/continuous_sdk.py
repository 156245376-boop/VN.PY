"""离线事件源与撮合替身；账户、数据引用、任务取消均保持独立状态。"""

from collections import Counter
from types import SimpleNamespace as NS

import pandas as pd

SYMBOLS = ['SHFE.rb2505', 'SHFE.rb2510', 'SHFE.rb2601', 'SHFE.rb2605']


def sample_events():
    result = []
    for day, index in [('2024-12-20', 0), ('2025-01-03', 0), ('2025-01-06', 1),
                       ('2026-01-05', 2), ('2026-01-06', 3)]:
        base = int(pd.Timestamp(day+' 09:00:00', tz='Asia/Shanghai').value)
        for minute in range(20):
            result.append(dict(now=base+minute*60_000_000_000, symbol=SYMBOLS[index],
                               price=[104, 103, 102, 101, 102, 103, 104][min(minute, 6)]))
    return result


class Finished(Exception):
    pass


class ContinuousSdkFixture:
    def __init__(self, events=None, *, faults=None):
        self.events = events or sample_events()
        self.faults = set(faults or [])
        self.calls = Counter()
        self.apis = []
        outer = self

        class Sim:
            def __init__(self, init_balance):
                outer.calls['TqSim'] += 1
                self.initial = init_balance
                self.fees = {}
                self.tqsdk_stat = {}
            def get_margin(self, symbol):
                return 1e9 if 'unaffordable' in outer.faults and symbol != SYMBOLS[0] else 1000
            def get_commission(self, symbol):
                return self.fees.get(symbol, 2)
            def set_commission(self, symbol, fee):
                self.fees[symbol] = fee

        class Backtest:
            def __init__(self, *, start_dt, end_dt):
                outer.calls['TqBacktest'] += 1
                self._start_dt = int(pd.Timestamp(start_dt, tz='Asia/Shanghai').value)
                self._end_dt = (int(pd.Timestamp(end_dt, tz='Asia/Shanghai').value)
                                +86400_000_000_000-1)
                self._current_dt = outer.events[0]['now']
                self._serials, self._generators = {}, {}

        class Api:
            def __init__(self, *, account, backtest, **kw):
                outer.calls['TqApi'] += 1
                self.account, self.backtest = account, backtest
                self._data, self.index, self.closed = {'notify': {}}, 0, False
                self.positions, self.orders, self.trades = {}, {}, {}
                self.quotes, self.serials, self.entries, self.targets = {}, {}, {}, []
                self.equity = NS(balance=account.initial, available=account.initial, commission=0)
                self.realized = 0
                outer.apis.append(self)

            def _print(self, *a, **kw):
                pass

            def current(self):
                return outer.events[min(self.index, len(outer.events)-1)]

            def get_quote(self, symbol):
                if symbol not in self.quotes:
                    self.quotes[symbol] = NS(underlying_symbol='', datetime='',
                        last_price=float('nan'),
                        price_tick=1, price_decs=0, volume_multiple=10,
                        open_min_limit_order_volume=1, expire_datetime=4102444800,
                        instrument_name=symbol, bid_price1=float('nan'), ask_price1=float('nan'))
                self.refresh()
                return self.quotes[symbol]

            def get_kline_serial(self, symbol, duration, data_length=200):
                key = (symbol, duration)
                if key not in self.serials:
                    self.serials[key] = (pd.DataFrame(), data_length)
                self.refresh()
                return self.serials[key][0]

            def get_tick_serial(self, symbol, **kw):
                if 'tick' in outer.faults:
                    raise RuntimeError('private-secret')
                return pd.DataFrame([{'datetime': self.current()['now']}])

            def get_trading_calendar(self, start_dt, end_dt):
                if 'calendar' in outer.faults:
                    raise RuntimeError('private-secret')
                days = {pd.Timestamp(e['now'], tz='UTC').tz_convert('Asia/Shanghai').date()
                        for e in outer.events}
                dates = pd.date_range(start_dt, end_dt, freq='D')
                return pd.DataFrame({'date': dates, 'trading': [d.date() in days for d in dates]})

            def refresh(self):
                e = self.current()
                self.backtest._current_dt = e['now']
                for symbol, quote in self.quotes.items():
                    index = SYMBOLS.index(symbol) if symbol in SYMBOLS else 0
                    quote.last_price = e['price']+index*100
                    quote.bid_price1 = quote.ask_price1 = quote.last_price
                    quote.datetime = str(pd.Timestamp(e['now'], tz='UTC')
                                         .tz_convert('Asia/Shanghai'))
                    quote.underlying_symbol = '' if 'mapping' in outer.faults else e['symbol']
                    if 'multiplier' in outer.faults and index:
                        quote.volume_multiple = 20
                for (symbol, _duration), (frame, length) in self.serials.items():
                    rows = []
                    for i, event in enumerate(outer.events[:self.index+1]):
                        if 'reference' in outer.faults and symbol != SYMBOLS[0]:
                            if event['now'] < e['now']:
                                continue
                        if 'prewarm' in outer.faults and event['now'] < int(pd.Timestamp(
                                '2025-01-03', tz='Asia/Shanghai').value):
                            continue
                        price = event['price']+SYMBOLS.index(symbol)*100
                        rows.append(dict(id=i, datetime=event['now'], open=price, close=price,
                                         high=price+1, low=price-1, volume=10, close_oi=30))
                    rows = rows[-length:]
                    frame.drop(frame.index, inplace=True)
                    for key in list(frame.columns):
                        frame.drop(columns=key, inplace=True)
                    new = pd.DataFrame(rows)
                    for key in new:
                        frame[key] = new[key]

            def get_account(self):
                return self.equity
            def get_position(self):
                return self.positions
            def get_order(self):
                return self.orders
            def get_trade(self):
                return self.trades

            def insert_order(self, symbol, direction, offset='', volume=0, **kw):
                oid = 'o'+str(len(self.orders))
                self.orders[oid] = NS(order_id=oid, symbol=symbol, direction=direction,
                    offset=offset, volume_left=volume, status='ALIVE',
                    is_error='reject' in outer.faults)
                return self.orders[oid]

            def wait_update(self, **kw):
                if 'stalled' in outer.faults:
                    return False
                if self.index+1 >= len(outer.events):
                    self.account.tqsdk_stat = dict(end_balance=self.equity.balance,
                                                    commission=self.equity.commission)
                    raise Finished()
                self.index += 1
                self.refresh()
                if 'disconnect' in outer.faults:
                    self._data['notify']['lost'] = {'code': 2019112911}
                for oid, order in self.orders.items():
                    if order.status == 'FINISHED' or order.is_error:
                        continue
                    if 'partial' in outer.faults and order.symbol != SYMBOLS[0]:
                        continue
                    price, qty = self.get_quote(order.symbol).last_price, order.volume_left
                    side = 1 if order.direction == 'BUY' else -1
                    position = self.positions.setdefault(order.symbol, NS(pos_long=0, pos_short=0))
                    if order.offset == 'OPEN':
                        if side > 0:
                            position.pos_long += qty
                        else:
                            position.pos_short += qty
                        self.entries[order.symbol] = price
                    else:
                        self.realized += (-side)*qty*10*(price-self.entries[order.symbol])
                        if side < 0:
                            position.pos_long -= qty
                        else:
                            position.pos_short -= qty
                    self.equity.commission += qty*self.account.get_commission(order.symbol)
                    tid = 't'+str(len(self.trades))
                    self.trades[tid] = NS(trade_id=tid, order_id=oid,
                        exchange_id='SHFE', instrument_id=order.symbol.split('.')[1],
                        direction=order.direction, offset=order.offset, volume=qty,
                        price=price, trade_date_time=self.current()['now'])
                    order.volume_left, order.status = 0, 'FINISHED'
                unrealized = sum((p.pos_long-p.pos_short)*10
                    *(self.get_quote(s).last_price-self.entries[s])
                    for s, p in self.positions.items())
                self.equity.balance = (self.account.initial+self.realized+unrealized
                                       -self.equity.commission)
                self.equity.available = self.equity.balance-1000*sum(
                    p.pos_long+p.pos_short for p in self.positions.values())
                return True

            def close(self):
                self.closed = True

        class Target:
            def __init__(self, api, symbol, **kw):
                self.api, self.symbol, self.cancelled = api, symbol, False
            def set_target_volume(self, target):
                self.api.targets.append((self.api.current()['now'], self.symbol, target))
                p = self.api.positions.get(self.symbol, NS(pos_long=0, pos_short=0))
                current = p.pos_long-p.pos_short
                if target != current:
                    self.api.insert_order(self.symbol, 'BUY' if target > current else 'SELL',
                                          offset='CLOSE' if current else 'OPEN',
                                          volume=abs(target-current))
            def cancel(self):
                self.cancelled = True
                for order in self.api.orders.values():
                    if order.symbol == self.symbol:
                        order.status = 'FINISHED'
            def is_finished(self):
                return self.cancelled

        self.sdk = NS(TqApi=Api, TqSim=Sim, TqBacktest=Backtest, TqAuth=lambda *a: object(),
                      TargetPosTask=Target, BacktestFinished=Finished)
