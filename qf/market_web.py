"""锁定 SDK 的窗口连接生命周期适配；不改变认证、行情或安装资源。"""

import asyncio
from contextlib import contextmanager
from importlib.metadata import version

import simplejson
from aiohttp import web
from tqsdk.channel import TqChan
from tqsdk.tqwebhelper import TqWebHelper


class WorkspaceWebHelper(TqWebHelper):
    async def connection_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(self.get_send_msg(self._data))
        channel = TqChan(self._api, last_only=True)
        self._conn_diff_chans.add(channel)
        peek = asyncio.Event()

        async def send_updates():
            while not ws.closed:
                await peek.wait()
                peek.clear()
                diff = await channel.recv()
                if diff is None:
                    return
                await ws.send_str(self.get_send_msg(diff))

        sender = asyncio.create_task(send_updates())
        try:
            # 接收关闭帧不再被“等待下一次数据”阻塞。
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    break
                packet = simplejson.loads(msg.data)
                if isinstance(packet, dict) and packet.get('aid') == 'peek_message':
                    peek.set()
        except (ValueError, ConnectionError, RuntimeError):
            pass
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            self._conn_diff_chans.discard(channel)
            await channel.close()
            await ws.close()
        return ws


@contextmanager
def workspace_web_helper(sdk):
    """只在本窗口唯一 TqApi 的同步构造期间替换工厂，实例创建后立即恢复。"""
    if getattr(sdk, '__name__', None) != 'tqsdk':
        yield
        return
    if version('tqsdk') != '3.10.2':
        raise RuntimeError('工作区图表适配只支持已锁定的 SDK')
    import tqsdk.api as api_module

    original = api_module.TqWebHelper
    api_module.TqWebHelper = WorkspaceWebHelper
    try:
        yield
    finally:
        api_module.TqWebHelper = original
