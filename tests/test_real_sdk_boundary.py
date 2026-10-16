"""运行真实 SDK 委托协程，网络边界用内存对象替换；不创建 TqApi 会话。"""

import asyncio
from types import SimpleNamespace

from tqsdk.lib.target_pos_task import InsertOrderTask

from qf.journal import Journal
from qf.runtime import tracked_api
from qf.safety import Guard


class Order(dict):
    def __getattr__(self, name):
        return self[name]


class Chan:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def send(self, message):
        pass


class BoundaryApi:
    def __init__(self, **kwargs):
        self._data = {"notify": {}}
        self.orders = {}

    def get_position(self):
        return {}

    def get_trade(self):
        return {}

    def get_order(self):
        return self.orders

    def insert_order(self, symbol, direction, offset, volume, limit_price=None, **kwargs):
        order = Order(order_id=kwargs["order_id"], status="FINISHED", is_error=False,
                      volume_orign=volume, volume_left=volume, trade_records={},
                      limit_price=limit_price)
        self.orders[order.order_id] = order
        return order

    def register_update_notify(self):
        return Chan()


def test_real_sdk_insert_task_preserves_positional_limit_price(tmp_path):
    journal = Journal.create(tmp_path, "paper", {})
    api = tracked_api(SimpleNamespace(TqApi=BoundaryApi), journal)
    guard = Guard(journal, "SHFE.rb2610")
    guard.start({}, {}, activate=True)
    api.execution_guard = guard
    task = object.__new__(InsertOrderTask)
    task._api, task._account = api, None
    task._symbol, task._direction, task._offset = "SHFE.rb2610", "BUY", "OPEN"
    task._volume, task._limit_price = 1, 3301.
    task._order_chan, task._trade_chan, task._trade_objs_chan = Chan(), None, None
    asyncio.run(task._run())
    assert len(api.orders) == 1
    assert next(iter(api.orders.values())).limit_price == 3301.
    assert journal.owned() == set(api.orders)
    journal.close()
