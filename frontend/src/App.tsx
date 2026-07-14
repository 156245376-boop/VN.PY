import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  CandlestickChart,
  Database,
  CalendarClock,
  FlaskConical,
  Grid3x3,
  Boxes,
  Plug,
  ShieldCheck,
  ShieldAlert,
  Cpu,
  Zap,
} from "lucide-react";
import { api, SystemStatus } from "./api";
import ConnectionPanel from "./panels/ConnectionPanel";
import LivePanel from "./panels/LivePanel";
import ChartPanel from "./panels/ChartPanel";
import DataPanel from "./panels/DataPanel";
import EventPanel from "./panels/EventPanel";
import BacktestPanel from "./panels/BacktestPanel";
import MatrixPanel from "./panels/MatrixPanel";
import StrategyPanel from "./panels/StrategyPanel";

type PanelKey =
  | "connection"
  | "live"
  | "chart"
  | "data"
  | "events"
  | "backtest"
  | "matrix"
  | "strategy";

const NAV: { key: PanelKey; label: string; icon: JSX.Element }[] = [
  { key: "connection", label: "连接配置", icon: <Plug size={16} /> },
  { key: "live", label: "实时行情", icon: <Activity size={16} /> },
  { key: "chart", label: "K 线图表", icon: <CandlestickChart size={16} /> },
  { key: "data", label: "历史数据", icon: <Database size={16} /> },
  { key: "events", label: "事件日历", icon: <CalendarClock size={16} /> },
  { key: "backtest", label: "单次回测", icon: <FlaskConical size={16} /> },
  { key: "matrix", label: "场景矩阵", icon: <Grid3x3 size={16} /> },
  { key: "strategy", label: "策略管理", icon: <Boxes size={16} /> },
];

export default function App() {
  const [panel, setPanel] = useState<PanelKey>("data");
  const [status, setStatus] = useState<SystemStatus | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.systemStatus());
    } catch {
      /* 后端未启动时静默 */
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const t = setInterval(refreshStatus, 5000);
    return () => clearInterval(t);
  }, [refreshStatus]);

  const toggleSafeMode = async () => {
    if (!status) return;
    await api.setSafeMode(!status.safe_mode);
    refreshStatus();
  };

  const gpuOn = status?.gpu.available ?? false;

  return (
    <div className="app">
      <div className="topbar">
        <span className="title">草老师的交易系统</span>
        <span className="muted small">{status?.version ? `v${status.version}` : ""}</span>
        <div className="spacer" />
        <span
          className={`badge ${gpuOn ? "gpu-on" : "gpu-off"}`}
          title={gpuOn ? status?.gpu.name ?? "" : status?.gpu.reason ?? "GPU 不可用"}
        >
          {gpuOn ? <Zap size={14} /> : <Cpu size={14} />}
          {gpuOn ? `GPU: ${status?.gpu.name}` : "GPU 不可用 (CPU 回落)"}
        </span>
        <span
          className={`badge ${status?.safe_mode ? "safe" : "live"}`}
          onClick={toggleSafeMode}
          style={{ cursor: "pointer" }}
          title="点击切换安全模式"
        >
          {status?.safe_mode ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
          {status?.safe_mode ? "安全模式" : "实盘可下单"}
        </span>
      </div>

      <div className="sidebar">
        {NAV.map((n) => (
          <div
            key={n.key}
            className={`nav-item ${panel === n.key ? "active" : ""}`}
            onClick={() => setPanel(n.key)}
          >
            {n.icon}
            <span>{n.label}</span>
          </div>
        ))}
      </div>

      <div className="content">
        {panel === "connection" && <ConnectionPanel onChange={refreshStatus} />}
        {panel === "live" && <LivePanel status={status} />}
        {panel === "chart" && <ChartPanel />}
        {panel === "data" && <DataPanel status={status} onChange={refreshStatus} />}
        {panel === "events" && <EventPanel />}
        {panel === "backtest" && <BacktestPanel />}
        {panel === "matrix" && <MatrixPanel status={status} />}
        {panel === "strategy" && <StrategyPanel />}
      </div>
    </div>
  );
}
