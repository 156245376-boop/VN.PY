"""行情白名单与中文检索，不创建 SDK 会话。"""

import math
import re

CONTINUOUS = re.compile(r"KQ\.m@(SHFE|DCE|CZCE|CFFEX|INE|GFEX)\.([A-Za-z]+)\Z")


def catalog_rows(raw_rows: list[dict]) -> list[dict]:
    result = {}
    for raw in raw_rows:
        symbol = raw.get("instrument_id", raw.get("continuous", ""))
        match = CONTINUOUS.fullmatch(symbol) if isinstance(symbol, str) else None
        if not match:
            continue
        exchange, product = match.groups()
        name = raw.get("instrument_name", raw.get("name", ""))
        result[symbol] = {"continuous": symbol,
                          "name": name[:80] if isinstance(name, str) and name else product,
                          "exchange": exchange, "product": product}
    return sorted(result.values(), key=lambda r: (r["exchange"], r["product"]))


def finite_number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and (value > 0 if positive else value >= 0) else None


def quote_row(catalog: dict, quote: dict, *, connected: bool) -> dict:
    price = finite_number(quote.get("last_price"), positive=True)
    settlement = finite_number(quote.get("pre_settlement"), positive=True)
    stamp = quote.get("datetime", "")
    stamp = stamp[:40] if isinstance(stamp, str) else ""
    underlying = quote.get("underlying_symbol", "")
    underlying = underlying if isinstance(underlying, str) and len(underlying) < 50 else ""
    state = "disconnected" if not connected else "ready" if price and stamp else "waiting"
    change = (price - settlement) / settlement * 100 if price and settlement else None
    return {**{key: catalog[key] for key in ("continuous", "name", "exchange", "product")},
            "underlying": underlying, "last_price": price,
            "change_percent": change,
            "volume": finite_number(quote.get("volume")),
            "open_interest": finite_number(quote.get("open_interest")),
            "quote_time": stamp, "data_state": state}


def filter_catalog(rows: list[dict], text: str, exchange: str | None) -> list[dict]:
    query = text.strip().casefold()
    return [row for row in rows if (not exchange or row["exchange"] == exchange)
            and query in " ".join(str(v) for v in row.values()).casefold()]
