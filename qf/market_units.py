"""当前国内期货报价单位白名单；来源和例外见 docs/market-data-display.md。"""

_GROUPS = {
    "SHFE": {
        "元/吨": "ad al ao br bu cu fu hc ni op pb rb ru sn sp ss wr zn",
        "元/克": "au", "元/千克": "ag",
    },
    "DCE": {
        "元/吨": "a b bz c cs eb eg i j jm l lh m p pg pp rr v y",
        "元/张": "bb", "元/立方米": "fb lg", "元/500千克": "jd",
    },
    "CZCE": {
        "元/吨": "AP CF CJ CY FG JR LR MA OI PF PK PL PM PR PX RI RM RS SA SF SH SM SR TA UR WH ZC",
    },
    "GFEX": {"元/吨": "si lc ps", "元/克": "pt pd"},
    "INE": {"元/吨": "bc lu nr", "元/桶": "sc", "点": "ec"},
    "CFFEX": {"点": "IC IF IH IM", "元/百元面值": "T TF TL TS"},
}
_UNITS = {(exchange, product.casefold()): unit
          for exchange, groups in _GROUPS.items()
          for unit, products in groups.items() for product in products.split()}


def price_unit(exchange: str, product: str) -> str:
    return _UNITS.get((exchange, product.casefold()), "单位待确认")
