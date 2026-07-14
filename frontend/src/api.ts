// 后端 API 客户端:REST 调用 + WebSocket 行情订阅。
// 请求走 Vite 代理转发到后端 8000 端口。

export interface GpuInfo {
  available: boolean;
  name?: string | null;
  total_mem_mb?: number | null;
  free_mem_mb?: number | null;
  used_mem_mb?: number | null;
  cuda_version?: string | null;
  reason?: string | null;
}

export interface SystemStatus {
  app: string;
  version: string;
  safe_mode: boolean;
  gpu: GpuInfo;
  akshare_available: boolean;
  gateway: {
    vnpy_available: boolean;
    connected: boolean;
    active_profile: string;
    profile_kind: string | null;
    subscribed: string[];
    safe_mode: boolean;
    mode: string;
  };
}

export interface Bar {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SymbolInfo {
  symbol: string;
  name?: string | null;
  exchange?: string | null;
  bar_count: number;
  first_ts?: number | null;
  last_ts?: number | null;
}

export interface StrategyParam {
  name: string;
  default: number;
  min: number;
  max: number;
  step: number;
}
export interface StrategyInfo {
  key: string;
  name: string;
  description: string;
  params: StrategyParam[];
}

export interface BacktestStats {
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  trade_count: number;
  win_rate: number;
  final_equity: number;
}

export interface BacktestResult {
  stats: BacktestStats;
  equity_curve: { ts: number; equity: number }[];
  backend: string;
}

export interface MatrixCell {
  symbol: string;
  interval: string;
  params: Record<string, number>;
  time_filter: Record<string, number>;
  event_filter: Record<string, unknown>;
  stats: BacktestStats;
}

export interface MatrixResult {
  cells: MatrixCell[];
  backend: string;
  elapsed_ms: number;
  combo_count: number;
}

export interface EventItem {
  id?: number;
  label: string;
  category: string;
  start_ts: number;
  end_ts: number;
  symbol?: string | null;
  source: string;
  note?: string | null;
}

export interface ConnectionProfile {
  name: string;
  kind: string;
  broker_id: string;
  user_id: string;
  password: string;
  app_id: string;
  auth_code: string;
  md_address: string;
  td_address: string;
}

export interface Connections {
  active: string;
  profiles: Record<string, ConnectionProfile>;
}

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  systemStatus: () => req<SystemStatus>("/api/system/status"),
  setSafeMode: (enabled: boolean) =>
    req<{ safe_mode: boolean }>("/api/system/safe-mode", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  getConnections: () => req<Connections>("/api/connections"),
  updateConnection: (key: string, profile: Partial<ConnectionProfile>) =>
    req("/api/connections", {
      method: "PUT",
      body: JSON.stringify({ key, profile }),
    }),
  setActive: (key: string) =>
    req("/api/connections/active", { method: "POST", body: JSON.stringify({ key }) }),

  gatewayConnect: () => req<{ ok: boolean; mode?: string; note?: string; error?: string }>(
    "/api/gateway/connect", { method: "POST" }),
  gatewayDisconnect: () => req("/api/gateway/disconnect", { method: "POST" }),
  subscribe: (symbol: string) =>
    req("/api/gateway/subscribe", { method: "POST", body: JSON.stringify({ symbol }) }),

  symbols: () => req<SymbolInfo[]>("/api/data/symbols"),
  bars: (symbol: string, interval: string, limit = 5000) =>
    req<{ symbol: string; interval: string; bars: Bar[] }>(
      `/api/data/bars?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=${limit}`),
  download: (symbol: string, start: string, end: string, interval: string) =>
    req("/api/data/download", {
      method: "POST",
      body: JSON.stringify({ symbol, start, end, interval }),
    }),
  importCsv: async (symbol: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/data/import-csv?symbol=${encodeURIComponent(symbol)}`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail ?? res.statusText);
    }
    return res.json();
  },

  events: (category?: string) =>
    req<EventItem[]>(`/api/events${category ? `?category=${category}` : ""}`),
  addEvent: (event: EventItem) =>
    req<EventItem>("/api/events", { method: "POST", body: JSON.stringify(event) }),
  deleteEvent: (id: number) => req(`/api/events/${id}`, { method: "DELETE" }),
  seedEvents: () => req<{ added: number }>("/api/events/seed", { method: "POST" }),
  detectAnomalies: (symbol: string, sigma: number) =>
    req<{ detected: EventItem[] }>("/api/events/detect-anomalies", {
      method: "POST",
      body: JSON.stringify({ symbol, sigma }),
    }),

  strategies: () => req<StrategyInfo[]>("/api/strategies"),
  backtest: (body: unknown) =>
    req<BacktestResult>("/api/backtest", { method: "POST", body: JSON.stringify(body) }),
  matrix: (body: unknown) =>
    req<MatrixResult>("/api/matrix", { method: "POST", body: JSON.stringify(body) }),
};

export function connectMarketWs(onMessage: (msg: any) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/market`);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  };
  return ws;
}
