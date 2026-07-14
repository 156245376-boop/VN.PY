import { useEffect, useRef, useState } from "react";
import { init, dispose, Chart } from "klinecharts";
import { Play } from "lucide-react";
import { api, BacktestResult, StrategyInfo, SymbolInfo } from "../api";

const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"];

function pct(x: number): string {
  return `${(x * 100).toFixed(2)}%`;
}

export default function BacktestPanel() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [symbol, setSymbol] = useState("");
  const [interval, setInterval] = useState("1m");
  const [strategy, setStrategy] = useState("double_ma");
  const [params, setParams] = useState<Record<string, number>>({});
  const [skipOpen, setSkipOpen] = useState(0);
  const [skipClose, setSkipClose] = useState(0);
  const [eventMode, setEventMode] = useState("none");
  const [eventCats, setEventCats] = useState<string[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    api.symbols().then((s) => {
      setSymbols(s);
      if (s.length) setSymbol(s[0].symbol);
    });
    api.strategies().then((s) => {
      setStrategies(s);
    });
  }, []);

  useEffect(() => {
    const info = strategies.find((s) => s.key === strategy);
    if (info) {
      const p: Record<string, number> = {};
      info.params.forEach((pp) => (p[pp.name] = pp.default));
      setParams(p);
    }
  }, [strategy, strategies]);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = init(hostRef.current);
    chartRef.current = chart;
    return () => {
      if (hostRef.current) dispose(hostRef.current);
    };
  }, []);

  useEffect(() => {
    if (!result || !chartRef.current) return;
    const data = result.equity_curve.map((p) => ({
      timestamp: p.ts * 1000,
      open: p.equity,
      high: p.equity,
      low: p.equity,
      close: p.equity,
      volume: 0,
    }));
    chartRef.current.applyNewData(data);
  }, [result]);

  const run = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await api.backtest({
        symbol,
        interval,
        strategy,
        params,
        time_filter: { skip_open_minutes: skipOpen, skip_close_minutes: skipClose },
        event_filter: { mode: eventMode, categories: eventCats },
      });
      setResult(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const info = strategies.find((s) => s.key === strategy);
  const st = result?.stats;

  return (
    <div>
      <h2 className="section-title">单次回测</h2>
      <p className="section-desc">
        单个策略的一次事件驱动回测,走 CPU 保证逻辑正确。可叠加时段过滤(开收盘前若干分钟不做)
        与事件过滤(排除/仅看某类事件)。
      </p>
      {err && <div className="notice warn">{err}</div>}

      <div className="card">
        <div className="row">
          <div className="field">
            <label>合约</label>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.length === 0 && <option value="">无数据</option>}
              {symbols.map((s) => (
                <option key={s.symbol}>{s.symbol}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>周期</label>
            <select value={interval} onChange={(e) => setInterval(e.target.value)}>
              {INTERVALS.map((i) => (
                <option key={i}>{i}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>策略</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          {info?.params.map((p) => (
            <div className="field" key={p.name}>
              <label>{p.name}</label>
              <input
                type="number"
                value={params[p.name] ?? p.default}
                step={p.step}
                onChange={(e) => setParams({ ...params, [p.name]: Number(e.target.value) })}
              />
            </div>
          ))}
        </div>

        <div className="row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>开盘后跳过(分钟)</label>
            <input type="number" value={skipOpen} onChange={(e) => setSkipOpen(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>收盘前跳过(分钟)</label>
            <input type="number" value={skipClose} onChange={(e) => setSkipClose(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>事件过滤</label>
            <select value={eventMode} onChange={(e) => setEventMode(e.target.value)}>
              <option value="none">不过滤</option>
              <option value="exclude">排除事件区间</option>
              <option value="only">仅事件区间</option>
            </select>
          </div>
          <div className="field">
            <label>事件分类</label>
            <div className="chips">
              {["macro", "geopolitical", "anomaly"].map((c) => (
                <span
                  key={c}
                  className={`chip ${eventCats.includes(c) ? "on" : ""}`}
                  onClick={() =>
                    setEventCats((prev) =>
                      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]
                    )
                  }
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
          <button onClick={run} disabled={busy || !symbol}>
            <Play size={15} /> {busy ? "回测中..." : "运行回测"}
          </button>
        </div>
      </div>

      {st && (
        <div className="card">
          <div className="stat-grid">
            <div className="stat">
              <div className="k">总收益</div>
              <div className={`v ${st.total_return >= 0 ? "pos" : "neg"}`}>{pct(st.total_return)}</div>
            </div>
            <div className="stat">
              <div className="k">年化</div>
              <div className={`v ${st.annual_return >= 0 ? "pos" : "neg"}`}>{pct(st.annual_return)}</div>
            </div>
            <div className="stat">
              <div className="k">最大回撤</div>
              <div className="v neg">{pct(st.max_drawdown)}</div>
            </div>
            <div className="stat">
              <div className="k">夏普</div>
              <div className="v">{st.sharpe.toFixed(2)}</div>
            </div>
            <div className="stat">
              <div className="k">交易次数</div>
              <div className="v">{st.trade_count}</div>
            </div>
            <div className="stat">
              <div className="k">胜率</div>
              <div className="v">{pct(st.win_rate)}</div>
            </div>
            <div className="stat">
              <div className="k">期末权益</div>
              <div className="v mono">{st.final_equity.toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <strong>权益曲线</strong>
        <div ref={hostRef} className="chart-host" style={{ height: 360, marginTop: 8 }} />
      </div>
    </div>
  );
}
