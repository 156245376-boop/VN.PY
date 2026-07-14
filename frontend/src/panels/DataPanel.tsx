import { useEffect, useRef, useState } from "react";
import { Download, Upload, RefreshCw } from "lucide-react";
import { api, SymbolInfo, SystemStatus } from "../api";

const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"];

function fmtTs(ts?: number | null): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ");
}

export default function DataPanel({
  status,
  onChange,
}: {
  status: SystemStatus | null;
  onChange: () => void;
}) {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [symbol, setSymbol] = useState("rb0");
  const [start, setStart] = useState("2024-01-01");
  const [end, setEnd] = useState("2024-06-30");
  const [interval, setInterval] = useState("1m");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ type: string; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      setSymbols(await api.symbols());
    } catch (e) {
      /* ignore */
    }
  };

  useEffect(() => {
    load();
  }, []);

  const doDownload = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r: any = await api.download(symbol, start, end, interval);
      setMsg({ type: "info", text: `下载完成:写入 ${r.written} 条 ${symbol}` });
      load();
      onChange();
    } catch (e: any) {
      setMsg({ type: "warn", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const doImport = async (file: File) => {
    setBusy(true);
    setMsg(null);
    try {
      const r: any = await api.importCsv(symbol, file);
      setMsg({
        type: "info",
        text: `导入完成:写入 ${r.written} 条,跳过 ${r.skipped} 行脏数据`,
      });
      load();
      onChange();
    } catch (e: any) {
      setMsg({ type: "warn", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2 className="section-title">历史数据管理</h2>
      <p className="section-desc">
        用 akshare 在线下载国内期货历史 K 线,或导入本地 CSV。数据以 1 分钟为基础存储,
        回测时可重采样到任意周期。
      </p>

      {!status?.akshare_available && (
        <div className="notice warn">
          akshare 未安装,在线下载不可用。可先用 CSV 导入,或安装依赖后重试。
        </div>
      )}
      {msg && <div className={`notice ${msg.type}`}>{msg.text}</div>}

      <div className="card">
        <div className="row">
          <div className="field">
            <label>合约代码</label>
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="如 rb0 / rb2410" />
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
            <label>开始日期</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>结束日期</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <button onClick={doDownload} disabled={busy || !status?.akshare_available}>
            <Download size={15} /> 下载入库
          </button>
          <button className="secondary" onClick={() => fileRef.current?.click()} disabled={busy}>
            <Upload size={15} /> 导入 CSV
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) doImport(f);
              e.target.value = "";
            }}
          />
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>
          CSV 需含列:时间/开/高/低/收(量可选)。表头支持中英文与常见别名。
        </p>
      </div>

      <div className="card">
        <div className="toolbar">
          <strong>已入库合约</strong>
          <button className="ghost" onClick={load}>
            <RefreshCw size={14} /> 刷新
          </button>
        </div>
        {symbols.length === 0 ? (
          <p className="muted">暂无数据,先下载或导入。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>合约</th>
                <th className="num">K 线数(1m)</th>
                <th>起始</th>
                <th>最新</th>
              </tr>
            </thead>
            <tbody>
              {symbols.map((s) => (
                <tr key={s.symbol}>
                  <td>{s.symbol}</td>
                  <td className="num mono">{s.bar_count.toLocaleString()}</td>
                  <td className="mono">{fmtTs(s.first_ts)}</td>
                  <td className="mono">{fmtTs(s.last_ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
