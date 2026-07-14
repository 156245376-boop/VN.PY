import { useEffect, useMemo, useState } from "react";
import { Grid3x3, Cpu, Zap } from "lucide-react";
import { api, MatrixResult, MatrixCell, StrategyInfo, SymbolInfo, SystemStatus } from "../api";

const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"];
const METRICS = [
  { key: "total_return", label: "总收益", pct: true },
  { key: "annual_return", label: "年化", pct: true },
  { key: "max_drawdown", label: "最大回撤", pct: true },
  { key: "sharpe", label: "夏普", pct: false },
  { key: "trade_count", label: "交易数", pct: false },
  { key: "win_rate", label: "胜率", pct: true },
] as const;

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`;
}

// 收益值映射到红绿热力色。
function heatColor(v: number, min: number, max: number): string {
  if (max === min) return "#1c252e";
  const t = (v - min) / (max - min);
  const r = Math.round(216 - t * 140);
  const g = Math.round(79 + t * 79);
  const b = 79;
  return `rgba(${r},${g},${b},0.35)`;
}

export default function MatrixPanel({ status }: { status: SystemStatus | null }) {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selSymbols, setSelSymbols] = useState<string[]>([]);
  const [selIntervals, setSelIntervals] = useState<string[]>(["1m", "5m"]);
  const [strategy, setStrategy] = useState("double_ma");
  const [gridText, setGridText] = useState("fast: 5, 10, 20\nslow: 30, 60, 120");
  const [excludeEvents, setExcludeEvents] = useState(false);
  const [skipOpenClose, setSkipOpenClose] = useState(false);
  const [preferGpu, setPreferGpu] = useState(true);
  const [result, setResult] = useState<MatrixResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [sortKey, setSortKey] = useState<string>("total_return");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.symbols().then((s) => {
      setSymbols(s);
      if (s.length) setSelSymbols([s[0].symbol]);
    });
    api.strategies().then(setStrategies);
  }, []);

  const parseGrid = (): Record<string, number[]> => {
    const grid: Record<string, number[]> = {};
    gridText.split("\n").forEach((line) => {
      const [k, v] = line.split(":");
      if (k && v) {
        const vals = v
          .split(",")
          .map((x) => Number(x.trim()))
          .filter((x) => !Number.isNaN(x));
        if (vals.length) grid[k.trim()] = vals;
      }
    });
    return grid;
  };

  const run = async () => {
    setBusy(true);
    setErr("");
    try {
      const time_filters = skipOpenClose
        ? [
            { skip_open_minutes: 0, skip_close_minutes: 0 },
            { skip_open_minutes: 15, skip_close_minutes: 15 },
          ]
        : [{ skip_open_minutes: 0, skip_close_minutes: 0 }];
      const event_filters = excludeEvents
        ? [
            { mode: "none", categories: [] },
            { mode: "exclude", categories: ["macro", "geopolitical", "anomaly"] },
          ]
        : [{ mode: "none", categories: [] }];
      const r = await api.matrix({
        symbols: selSymbols,
        intervals: selIntervals,
        strategy,
        param_grid: parseGrid(),
        time_filters,
        event_filters,
        prefer_gpu: preferGpu,
      });
      setResult(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const sortedCells = useMemo(() => {
    if (!result) return [];
    const cells = [...result.cells];
    cells.sort((a, b) => (b.stats as any)[sortKey] - (a.stats as any)[sortKey]);
    return cells;
  }, [result, sortKey]);

  const returns = sortedCells.map((c) => c.stats.total_return);
  const minR = Math.min(...returns, 0);
  const maxR = Math.max(...returns, 0);

  const toggle = (arr: string[], setArr: (v: string[]) => void, v: string) =>
    setArr(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const gpuOn = status?.gpu.available;

  return (
    <div>
      <h2 className="section-title">场景矩阵</h2>
      <p className="section-desc">
        同一策略在多品种 × 多周期 × 时段/事件过滤 × 参数网格下的批量并行回测。组合数很大时
        用 GPU 显著加速;GPU 不可用会自动回落 CPU,结果一致。
      </p>
      {err && <div className="notice warn">{err}</div>}

      <div className="card">
        <div className="row">
          <div className="field" style={{ minWidth: 200 }}>
            <label>品种(多选)</label>
            <div className="chips">
              {symbols.length === 0 && <span className="muted small">无数据</span>}
              {symbols.map((s) => (
                <span
                  key={s.symbol}
                  className={`chip ${selSymbols.includes(s.symbol) ? "on" : ""}`}
                  onClick={() => toggle(selSymbols, setSelSymbols, s.symbol)}
                >
                  {s.symbol}
                </span>
              ))}
            </div>
          </div>
          <div className="field" style={{ minWidth: 200 }}>
            <label>周期(多选)</label>
            <div className="chips">
              {INTERVALS.map((i) => (
                <span
                  key={i}
                  className={`chip ${selIntervals.includes(i) ? "on" : ""}`}
                  onClick={() => toggle(selIntervals, setSelIntervals, i)}
                >
                  {i}
                </span>
              ))}
            </div>
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
        </div>

        <div className="row" style={{ marginTop: 10 }}>
          <div className="field" style={{ flex: 1, minWidth: 260 }}>
            <label>参数网格(每行 名称: 值1, 值2, ...)</label>
            <textarea
              value={gridText}
              onChange={(e) => setGridText(e.target.value)}
              rows={3}
              style={{
                background: "var(--panel-2)",
                border: "1px solid var(--border)",
                color: "var(--text)",
                borderRadius: 6,
                padding: 8,
                fontFamily: "monospace",
                resize: "vertical",
              }}
            />
          </div>
        </div>

        <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
          <label className="switch" onClick={() => setExcludeEvents(!excludeEvents)}>
            <span className={`track ${excludeEvents ? "on" : ""}`}>
              <span className="knob" />
            </span>
            对比「排除事件 vs 全时段」
          </label>
          <label className="switch" onClick={() => setSkipOpenClose(!skipOpenClose)}>
            <span className={`track ${skipOpenClose ? "on" : ""}`}>
              <span className="knob" />
            </span>
            对比「开收盘前 15 分钟不做 vs 全做」
          </label>
          <label className="switch" onClick={() => setPreferGpu(!preferGpu)} title={gpuOn ? "" : "GPU 不可用,将回落 CPU"}>
            <span className={`track ${preferGpu ? "on" : ""}`}>
              <span className="knob" />
            </span>
            {preferGpu ? <Zap size={14} /> : <Cpu size={14} />}
            {preferGpu ? "优先 GPU" : "使用 CPU"}
          </label>
          <button onClick={run} disabled={busy || selSymbols.length === 0 || selIntervals.length === 0}>
            <Grid3x3 size={15} /> {busy ? "运行中..." : "运行矩阵"}
          </button>
        </div>
      </div>

      {result && (
        <div className="card">
          <div className="toolbar">
            <span className="badge">
              后端:{result.backend === "gpu" ? "GPU" : "CPU"}
            </span>
            <span className="badge">组合数:{result.combo_count}</span>
            <span className="badge">耗时:{result.elapsed_ms} ms</span>
            <div className="field">
              <label className="small">排序</label>
              <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                {METRICS.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ maxHeight: 460, overflow: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>品种</th>
                  <th>周期</th>
                  <th>参数</th>
                  <th>时段</th>
                  <th>事件</th>
                  {METRICS.map((m) => (
                    <th key={m.key} className="num" onClick={() => setSortKey(m.key)}>
                      {m.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedCells.map((c, i) => (
                  <tr key={i}>
                    <td>{c.symbol}</td>
                    <td>{c.interval}</td>
                    <td className="mono small">
                      {Object.entries(c.params)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(" ") || "默认"}
                    </td>
                    <td className="small">
                      {c.time_filter.skip_open_minutes || c.time_filter.skip_close_minutes
                        ? `跳${c.time_filter.skip_open_minutes}/${c.time_filter.skip_close_minutes}`
                        : "全时段"}
                    </td>
                    <td className="small">
                      {(c.event_filter as any).mode === "exclude" ? "排除事件" : "全部"}
                    </td>
                    <td
                      className="num heatcell"
                      style={{ background: heatColor(c.stats.total_return, minR, maxR) }}
                    >
                      {pct(c.stats.total_return)}
                    </td>
                    <td className="num">{pct(c.stats.annual_return)}</td>
                    <td className="num neg">{pct(c.stats.max_drawdown)}</td>
                    <td className="num">{c.stats.sharpe.toFixed(2)}</td>
                    <td className="num">{c.stats.trade_count}</td>
                    <td className="num">{pct(c.stats.win_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
