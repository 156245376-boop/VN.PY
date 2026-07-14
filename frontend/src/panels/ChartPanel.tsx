import { useEffect, useRef, useState } from "react";
import { init, dispose, Chart } from "klinecharts";
import { api, SymbolInfo } from "../api";

const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"];

export default function ChartPanel() {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [symbol, setSymbol] = useState("");
  const [interval, setInterval] = useState("1m");
  const [loading, setLoading] = useState(false);
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    api.symbols().then((s) => {
      setSymbols(s);
      if (s.length && !symbol) setSymbol(s[0].symbol);
    });
  }, []);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = init(hostRef.current);
    chartRef.current = chart;
    chart?.createIndicator("VOL", false, { id: "vol_pane" });
    return () => {
      if (hostRef.current) dispose(hostRef.current);
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    setEmpty(false);
    api
      .bars(symbol, interval, 5000)
      .then((r) => {
        const data = r.bars.map((b) => ({
          timestamp: b.ts * 1000,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
          volume: b.volume,
        }));
        setEmpty(data.length === 0);
        chartRef.current?.applyNewData(data);
      })
      .finally(() => setLoading(false));
  }, [symbol, interval]);

  return (
    <div>
      <h2 className="section-title">K 线图表</h2>
      <div className="card">
        <div className="toolbar">
          <div className="field">
            <label>合约</label>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.length === 0 && <option value="">无数据</option>}
              {symbols.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>周期</label>
            <div className="chips">
              {INTERVALS.map((i) => (
                <span
                  key={i}
                  className={`chip ${interval === i ? "on" : ""}`}
                  onClick={() => setInterval(i)}
                >
                  {i}
                </span>
              ))}
            </div>
          </div>
          {loading && <span className="spinner">加载中...</span>}
        </div>
        {empty && (
          <div className="notice warn">该合约暂无数据,请先在「历史数据」面板下载或导入。</div>
        )}
        <div ref={hostRef} className="chart-host" />
      </div>
    </div>
  );
}
