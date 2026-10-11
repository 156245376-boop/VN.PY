"""交易日判定 —— 全系统唯一的「时间戳 → 交易日」出口(R3.4)。

**为什么必须唯一**:夜盘 21:00–02:30 归属其后的交易日,周五夜盘归属下周一,
节前夜盘整体停盘而非顺延。任何一处用 `dt.date()` 或工作日推算替代本模块,
表现都是**静默**的 —— 1 分钟 Bar 完全正常,而日线聚合、单日亏损限额、结算 PnL
与「入场后第几根」全部错位。所以 R3.4 要求只有一个函数,并且它在这里。

**为什么时段按「交易所 + 品种」查**:夜盘的存在与否和收盘时间都因品种而异
(23:00 / 01:00 / 02:30 三档,部分品种无夜盘),且这些定义随历史变化(R3.2)。
只按交易所查会把"该品种有没有夜盘"这个事实抹平;只按品种查则依赖"各交易所
品种代码大写后互不重名"这一未经核对的前提,一旦重名就会静默串用夜盘时间。

**为什么拒绝 naive 时间戳**:本模块是交易日的唯一出口,时区转换只应发生在数据源
入口(R10.6)。到这里还不带时区,说明上游转换点漏了;若按北京时间猜,UTC 时刻
会被静默错开 8 小时,夜盘时间戳被归到当天而不是下一个交易日。

入参形态对实施计划的验证片段有一处修订:原写 `to_trading_day(dt, SHFE)`,
实际为 `to_trading_day(moment, exchange, product)`,理由同上。计划文本已同步(R26.8)。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from core import (
    CHINA_TZ,
    CalendarMissing,
    Exchange,
    NotInTradingSession,
    SessionSpecMissing,
)
from meta.models import (
    SessionKind,
    SessionWindow,
    TradingDayRecord,
    TradingSessionSpec,
)
from meta.store import ReferenceDataStore
from meta.symbols import split_canonical

__all__ = ["TradingCalendar"]

#: 向后搜索"下一个交易日"的窗口长度。取 40 天是为了跨过最长的连续休市
#: (春节与国庆各约 8–9 个自然日)并留出余量。搜索不设下限但不设代价:
#: 到达覆盖边界时会抛 CalendarMissing,而不会把"数据没了"当成"没有下一个交易日"。
_MAX_HOLIDAY_LOOKAHEAD_DAYS = 40


class TradingCalendar:
    """交易日与交易时段判定的唯一实现。

    构造时注入 `ReferenceDataStore` —— 本类不读文件、不连网络、不缓存磁盘状态(R3.1)。
    同一个 store 上重复调用同一入参返回相同结果。
    """

    __slots__ = ("_store",)

    def __init__(self, store: ReferenceDataStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # R3.4–R3.7:时间戳 → 交易日
    # ------------------------------------------------------------------

    def to_trading_day(self, moment: datetime, exchange: Exchange, product: str) -> date:
        """把时间戳映射为 Trading_Day(R3.4)。

        Args:
            moment: **必须带时区**。naive 输入直接拒绝,不猜时区。
            exchange: 品种所属交易所,与 product 共同定位时段定义。
            product: 品种代码,大小写均可,内部统一转为大写后查询。

        Returns:
            该时刻所属的 Trading_Day。夜盘归属**其后**的交易日(R3.5):
            周五 21:30 返回下周一(R3.6)。

        Raises:
            ValueError: moment 不带时区。
            NotInTradingSession: 时刻不落在该品种任何时段内,或当晚夜盘按公告
                停盘(R3.7)。归入「记录并跳过」,调用方丢弃该 Tick 并计数(R3.10)。
            SessionSpecMissing: 该品种在该日无时段定义。归入「记录并跳过」(R32.7)。
            CalendarMissing: 判定所需日期超出日历覆盖范围(R3.13),属停机类。
        """
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError(
                f"{moment.isoformat()} 不带时区。交易日判定拒绝猜测时区:时区转换只应"
                f"发生在数据源入口(R10.6),按北京时间猜会把 UTC 时刻静默错开 8 小时"
            )
        local = moment.astimezone(CHINA_TZ)
        day = local.date()
        clock = local.time()

        spec = self._spec(exchange, product, day)
        for window in spec.windows:
            if not window.covers_head(clock):
                continue
            owner = self._owner_for_head(spec, window, day)
            if owner is not None:
                return owner

        # 跨零点窗口的尾段:区间起于前一自然日,延续到本自然日的凌晨。
        # 注意此时 `day` 本身可以不是交易日(周五夜盘延续到周六凌晨)。
        previous = day - timedelta(days=1)
        if self._is_trading_day(previous):
            previous_spec = self._spec(exchange, product, previous)
            for window in previous_spec.windows:
                if window.covers_tail(clock):
                    return self._night_owner(previous)

        raise NotInTradingSession(
            f"{product} 在 {local.isoformat()} 不落在任何 Trading_Session 内;"
            f"该 Tick 应被丢弃并计入计数型日志(R3.10)"
        )

    def _owner_for_head(
        self, spec: TradingSessionSpec, window: SessionWindow, day: date
    ) -> date | None:
        """处理落在「本自然日开始」的窗口内的时刻,返回其交易日或 None。

        **任何时段都只能起于一个交易日**,所以第一步先否定非交易日。漏掉这道检查的
        表现是:节假日 21:30 的时间戳被分配给节后第一个交易日 —— 凭空为一个不存在
        的行情造出交易日,而且不报错。夜盘竞价(20:55–21:00)同理,它随夜盘一起停。
        """
        if not self._is_trading_day(day):
            return None
        if window.kind is SessionKind.NIGHT:
            return self._night_owner(day)
        if window.kind is SessionKind.DAY:
            return day
        # 集合竞价:本身不给归属,由它紧接着的那个交易时段决定(R5.11 要求集合竞价
        # 行情不进 Bar 序列,但仍需能归属到某个交易日以便记账)。
        following = [
            candidate
            for candidate in spec.windows
            if candidate.kind is not SessionKind.CALL_AUCTION
            and candidate.start_minute >= window.end_minute
        ]
        if not following:
            return None
        next_window = min(following, key=lambda candidate: candidate.start_minute)
        if next_window.kind is SessionKind.NIGHT:
            return self._night_owner(day)
        return day

    def _night_owner(self, evening_of: date) -> date:
        """返回 `evening_of` 晚间夜盘所归属的交易日。

        夜盘归属其后的第一个交易日;若该交易日的夜盘按公告停盘,则**该时段不存在**,
        不顺延到节后(R3.7)。
        """
        owner = self._next_trading_day(evening_of)
        if not self._record(owner).preceded_by_night_session:
            raise NotInTradingSession(
                f"{evening_of} 晚间无夜盘:{owner} 的夜盘按交易所公告停盘(R3.7)。"
                f"停盘意味着该时段不存在,而非顺延到节后"
            )
        return owner

    # ------------------------------------------------------------------
    # R3.8–R3.13:查询面
    # ------------------------------------------------------------------

    def is_trading_day(self, day: date) -> bool:
        """该自然日是否为交易日(R3.9)。

        Raises:
            CalendarMissing: 日期超出日历覆盖范围(R3.13)—— 不猜。
        """
        return bool(self._days(day, day))

    def is_in_session(self, symbol: str, moment: datetime) -> bool:
        """该时间戳是否落在该合约的 Trading_Session 内(R3.8)。

        只有「不落在任何时段」返回 False;日历数据缺口仍会抛 CalendarMissing,
        因为那是数据缺陷而不是"不在盘中"。
        """
        product, _yymm, exchange = split_canonical(symbol)
        try:
            self.to_trading_day(moment, exchange, product)
        except NotInTradingSession:
            return False
        return True

    def sessions_for(self, exchange: Exchange, product: str, asof: date) -> TradingSessionSpec:
        """返回该品种在 asof 生效的时段定义(R3.3)。"""
        return self._spec(exchange, product, asof)

    def call_auctions(
        self, exchange: Exchange, product: str, asof: date
    ) -> tuple[SessionWindow, ...]:
        """返回该品种在 asof 的集合竞价时段区间(R3.12)。

        返回元组而非单值:夜盘与日盘各有一段竞价,合成一个会丢掉其中一段。
        """
        return self._spec(exchange, product, asof).call_auction_windows

    def expected_bar_count(self, symbol: str, trading_day: date) -> int:
        """返回该合约在该交易日应存在的 1 分钟 Bar 数量(R3.11)。

        集合竞价区间**不计入**:R5.11 要求把竞价行情排除在 Bar 序列之外,
        计入会让每天的质量检查凭空多出十分钟缺口。

        非交易日返回 0。超出日历覆盖范围仍抛 CalendarMissing —— 前者是确定的
        事实,后者是数据缺失,二者不能混为一谈(R3.13)。
        """
        if not self._days(trading_day, trading_day):
            return 0
        product, _yymm, exchange = split_canonical(symbol)
        spec = self._spec(exchange, product, trading_day)
        total = sum(window.duration_minutes() for window in spec.day_windows)
        if spec.night_windows and self._record(trading_day).preceded_by_night_session:
            total += sum(window.duration_minutes() for window in spec.night_windows)
        return total

    # ------------------------------------------------------------------
    # 内部:参考数据访问
    # ------------------------------------------------------------------

    def _days(self, start: date, end: date) -> tuple[TradingDayRecord, ...]:
        """读取 [start, end] 内的交易日;越界抛错,右端自动收敛到覆盖上界。"""
        first, last = self._store.coverage()
        if start < first or start > last:
            raise CalendarMissing(
                f"请求日期 {start} 超出交易日历覆盖范围 [{first}, {last}](R3.13)。"
                f"抛错而非返回推测结果:猜错交易日会使日线聚合、单日亏损限额与"
                f"结算 PnL 全部静默出错,而 1 分钟 Bar 看起来完全正常"
            )
        clamped = min(end, last)
        if clamped < start:
            return ()
        return tuple(self._store.trading_days(start, clamped))

    def _is_trading_day(self, day: date) -> bool:
        return bool(self._days(day, day))

    def _record(self, day: date) -> TradingDayRecord:
        records = self._days(day, day)
        if not records:
            raise CalendarMissing(f"{day} 不是交易日,取不到其夜盘归属记录")
        return records[0]

    def _next_trading_day(self, day: date) -> date:
        records = self._days(
            day + timedelta(days=1),
            day + timedelta(days=_MAX_HOLIDAY_LOOKAHEAD_DAYS),
        )
        if not records:
            raise CalendarMissing(
                f"{day} 之后 {_MAX_HOLIDAY_LOOKAHEAD_DAYS} 天内没有交易日记录;"
                f"日历数据不完整或覆盖已到尽头,无法判定夜盘归属"
            )
        return records[0].day

    def _spec(self, exchange: Exchange, product: str, asof: date) -> TradingSessionSpec:
        key = product.strip().upper()
        spec = self._store.session_spec(exchange, key, asof)
        if spec.exchange is not exchange or spec.product != key or not spec.covers(asof):
            raise SessionSpecMissing(
                f"{exchange.value}.{key} 在 {asof} 无生效时段定义(存储返回了 "
                f"{spec.exchange.value}.{spec.product} {spec.effective_from}–"
                f"{spec.effective_to});不得回退到最近的可用版本或别的品种(R3.2)"
            )
        return spec
