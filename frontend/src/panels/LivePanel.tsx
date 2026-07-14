import { useEffect, useRef, useState } from "react";
import { Plug, PlugZap, Plus } from "lucide-react";
import { api, connectMarketWs, SystemStatus } from "../api";

interface Tick {
  symbol: string;
  price: number;
  ts: number;
  prev?: number;
}

export default function LivePanel({ status }: { status: SystemStatus | null }) {
  const [ticks, setTicks] = useState<Record<string, Tick>>({});
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [sym, setSym] = useState("rb0");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = connectMarketWs((msg) => {
      if (msg.type === "tick") {
        setTicks((prev) => ({
          ...prev,
          [msg.symbol]: {
            symbol: msg.symbol,
            price: msg.price,
            ts: msg.ts,
            prev: prev[msg.symbol]?.price,
          },
        }));
      }
    });
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    return () => ws.close();
  }, []);

  const doConnect = async () => {
    const r = await api.gatewayConnect();
    setMode(r.mode ?? "");
    setNote(r.note ?? r.error ?? "");
    if (r.ok) await api.subscribe(sym);
  };

  const addSub = async () => {
    await api.subscribe(sym);
  };

  const vnpyOk = status?.gateway.vnpy_available;

  return (
    <div>
      <h2 className="section-title">实时行情</h2>
      <p className="section-desc">
        通过 CTP(SimNow / 实盘)订阅合约,tick 聚合为 1 秒 / 1 分钟 K 线并实时推送。
        国内期货交易所每 500 毫秒推送一笔。
      </p>

      {!vnpyOk && (
        <div className="notice warn">
          vnpy / vnpy_ctp 未安装,无法连接真实 CTP 行情。点击连接将启动本地行情模拟器,
          仅用于界面联调;装好依赖并配置 SimNow 后即可接入真实实时行情。
        </div>
      )}
      {note && <div className="notice info">{note}</div>}

      <div className="card">
        <div className="toolbar">
          <span className={`badge ${connected ? "safe" : ""}`}>
            {connected ? <PlugZap size={14} /> : <Plug size={14} />}
            {connected ? `已连接 (${mode || status?.gateway.mode || "idle"})` : "未连接推送"}
          </span>
          <div className="field">
            <input value={sym} onChange={(e) => setSym(e.target.value)} placeholder="合约代码" />
          </div>
          <button onClick={doConnect}>连接行情</button>
          <button className="secondary" onClick={addSub}>
            <Plus size={14} /> 订阅
          </button>
        </div>
      </div>

      <div className="card">
        <strong>最新报价</strong>
        {Object.keys(ticks).length === 0 ? (
          <p className="muted" style={{ marginTop: 10 }}>
            尚无行情推送。点击「连接行情」并订阅合约后,报价会实时刷新。
          </p>
        ) : (
          <table style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>合约</th>
                <th className="num">最新价</th>
                <th className="num">方向</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(ticks).map((t) => {
                const up = t.prev != null && t.price >= t.prev;
                return (
                  <tr key={t.symbol}>
                    <td>{t.symbol}</td>
                    <td className={`num tick-price ${up ? "pos" : "neg"}`}>{t.price.toFixed(2)}</td>
                    <td className={`num ${up ? "pos" : "neg"}`}>{up ? "▲" : "▼"}</td>
                    <td className="mono">{new Date(t.ts * 1000).toLocaleTimeString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
