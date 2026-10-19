"""逐实际合约保存 SDK 模拟费用和保证金模型。"""

from qf.research_config import decimal_value as dec
from qf.safety import Frozen
from qf.trade_risk import ContractSpec


def contract_spec(api, account, symbol, quote, *, paper, multiplier):
    margin = getattr(quote, 'margin', float('nan')) if paper else account.get_margin(symbol)
    fee = getattr(quote, 'commission', float('nan')) if paper else account.get_commission(symbol)
    try:
        spec = ContractSpec(symbol, dec(quote.price_tick), dec(quote.volume_multiple),
            int(quote.open_min_limit_order_volume), 1, dec(margin), dec(fee)*multiplier,
            'SDK_quote_model' if paper else 'SDK_TqSim_per_lot_model')
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise Frozen('sdk_cost_missing') from None
    if not paper:
        account.set_commission(symbol, float(spec.commission_per_lot))
    return spec
