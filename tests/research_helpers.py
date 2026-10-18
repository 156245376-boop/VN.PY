"""研究实验测试输入，金额是测试夹具，不是产品推荐仓位。"""


def config_data():
    return dict(schema_version=1, strategy_id="ma_cross", strategy_version=1,
                name="双均线测试", symbol="SHFE.rb2505", continuous="KQ.m@SHFE.rb",
                bar_seconds=300, fast_period=5, slow_period=20, start="2025-03-03",
                end="2025-03-07", initial_balance="100000", precision="minute",
                timeout_seconds=30, execution_timeout_seconds=30,
                risk=dict(sizing="risk_budget", fixed_lots=2, risk_budget="1000",
                          stop_ticks=50, max_lots=10, max_margin_ratio="0.5",
                          take_profit_mode="r_multiple", take_profit_value="3",
                          stairs_enabled=True, first_trigger_r="1", first_offset_ticks=1,
                          second_trigger_r="2", second_lock_r="0.5"))
