import { useEffect, useState } from "react";
import { Trash2, Plus, Sparkles, Radar } from "lucide-react";
import { api, EventItem } from "../api";

const CATEGORIES = [
  { key: "macro", label: "宏观" },
  { key: "geopolitical", label: "地缘" },
  { key: "anomaly", label: "异常波动" },
];

function toTs(date: string): number {
  return Math.floor(new Date(date + "T00:00:00Z").getTime() / 1000);
}
function fromTs(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

export default function EventPanel() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("macro");
  const [start, setStart] = useState("2024-01-01");
  const [end, setEnd] = useState("2024-01-02");
  const [anomalySym, setAnomalySym] = useState("rb0");
  const [sigma, setSigma] = useState(3);
  const [msg, setMsg] = useState("");

  const load = async () => setEvents(await api.events(filter || undefined));

  useEffect(() => {
    load();
  }, [filter]);

  const add = async () => {
    if (!label) return;
    await api.addEvent({
      label,
      category,
      start_ts: toTs(start),
      end_ts: toTs(end) + 86399,
      source: "manual",
    });
    setLabel("");
    load();
  };

  const seed = async () => {
    const r = await api.seedEvents();
    setMsg(`已写入 ${r.added} 条预置事件种子`);
    load();
    setTimeout(() => setMsg(""), 2500);
  };

  const detect = async () => {
    try {
      const r = await api.detectAnomalies(anomalySym, sigma);
      setMsg(`检测到 ${r.detected.length} 个异常波动日 (${anomalySym})`);
    } catch (e: any) {
      setMsg(e.message);
    }
    load();
    setTimeout(() => setMsg(""), 3000);
  };

  return (
    <div>
      <h2 className="section-title">事件日历</h2>
      <p className="section-desc">
        标注宏观、地缘等事件区间,或自动检测异常波动日。回测时可按分类排除或仅观察这些时段,
        用于对比「避开重大事件」与「全时段」的策略表现差异。
      </p>
      {msg && <div className="notice info">{msg}</div>}

      <div className="card">
        <div className="row">
          <div className="field">
            <label>事件标签</label>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="如 美联储议息" />
          </div>
          <div className="field">
            <label>分类</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>起</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>止</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <button onClick={add}>
            <Plus size={15} /> 添加
          </button>
          <button className="secondary" onClick={seed}>
            <Sparkles size={15} /> 写入种子
          </button>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>异常检测合约</label>
            <input value={anomalySym} onChange={(e) => setAnomalySym(e.target.value)} />
          </div>
          <div className="field">
            <label>阈值 (σ)</label>
            <input
              type="number"
              step="0.5"
              value={sigma}
              onChange={(e) => setSigma(Number(e.target.value))}
            />
          </div>
          <button className="secondary" onClick={detect}>
            <Radar size={15} /> 自动检测异常
          </button>
        </div>
      </div>

      <div className="card">
        <div className="toolbar">
          <strong>事件列表</strong>
          <div className="chips">
            <span className={`chip ${filter === "" ? "on" : ""}`} onClick={() => setFilter("")}>
              全部
            </span>
            {CATEGORIES.map((c) => (
              <span
                key={c.key}
                className={`chip ${filter === c.key ? "on" : ""}`}
                onClick={() => setFilter(c.key)}
              >
                {c.label}
              </span>
            ))}
          </div>
        </div>
        {events.length === 0 ? (
          <p className="muted">暂无事件。可添加或写入种子。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>标签</th>
                <th>分类</th>
                <th>起</th>
                <th>止</th>
                <th>来源</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{e.label}</td>
                  <td>{e.category}</td>
                  <td className="mono">{fromTs(e.start_ts)}</td>
                  <td className="mono">{fromTs(e.end_ts)}</td>
                  <td className="muted">{e.source}</td>
                  <td>
                    <button className="ghost" onClick={() => e.id && api.deleteEvent(e.id).then(load)}>
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
