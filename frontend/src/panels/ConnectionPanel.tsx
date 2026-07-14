import { useEffect, useState } from "react";
import { CheckCircle2, Save } from "lucide-react";
import { api, Connections, ConnectionProfile } from "../api";

const FIELDS: { key: keyof ConnectionProfile; label: string; secret?: boolean }[] = [
  { key: "name", label: "显示名称" },
  { key: "broker_id", label: "经纪商代码" },
  { key: "user_id", label: "用户名" },
  { key: "password", label: "密码", secret: true },
  { key: "app_id", label: "AppID (产品名称)" },
  { key: "auth_code", label: "授权码", secret: true },
  { key: "md_address", label: "行情前置地址" },
  { key: "td_address", label: "交易前置地址" },
];

export default function ConnectionPanel({ onChange }: { onChange: () => void }) {
  const [conns, setConns] = useState<Connections | null>(null);
  const [editing, setEditing] = useState<string>("simnow");
  const [draft, setDraft] = useState<Partial<ConnectionProfile>>({});
  const [msg, setMsg] = useState("");

  const load = async () => {
    const c = await api.getConnections();
    setConns(c);
    setDraft(c.profiles[editing] ?? {});
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (conns) setDraft(conns.profiles[editing] ?? {});
  }, [editing]);

  const save = async () => {
    await api.updateConnection(editing, draft);
    setMsg("已保存连接档");
    load();
    onChange();
    setTimeout(() => setMsg(""), 2500);
  };

  const activate = async (key: string) => {
    await api.setActive(key);
    load();
    onChange();
  };

  if (!conns) return <p className="muted">加载中...</p>;

  const editingProfile = conns.profiles[editing];
  const isLive = editingProfile?.kind === "live";

  return (
    <div>
      <h2 className="section-title">连接配置</h2>
      <p className="section-desc">
        管理 SimNow 仿真与实盘(华西期货)两套连接档。实盘需向期货公司申请穿透式监管的
        AppID 与授权码。密码与授权码在界面上脱敏显示,保存时留空或占位则不会覆盖已存值。
      </p>
      {msg && <div className="notice info">{msg}</div>}

      <div className="card">
        <div className="toolbar">
          {Object.entries(conns.profiles).map(([key, p]) => (
            <span
              key={key}
              className={`chip ${editing === key ? "on" : ""}`}
              onClick={() => setEditing(key)}
            >
              {p.name}
              {conns.active === key && <CheckCircle2 size={13} style={{ marginLeft: 4 }} />}
            </span>
          ))}
          <div className="spacer" style={{ flex: 1 }} />
          {conns.active === editing ? (
            <span className="badge safe">当前使用</span>
          ) : (
            <button className="secondary" onClick={() => activate(editing)}>
              设为当前
            </button>
          )}
        </div>

        {isLive && (
          <div className="notice danger">
            实盘账号:研发期请保持顶栏「安全模式」开启,系统会拦截一切实盘自动下单。
          </div>
        )}

        <div className="row">
          {FIELDS.map((f) => (
            <div className="field" key={f.key}>
              <label>{f.label}</label>
              <input
                type={f.secret ? "password" : "text"}
                value={(draft[f.key] as string) ?? ""}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
              />
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12 }}>
          <button onClick={save}>
            <Save size={15} /> 保存
          </button>
        </div>
      </div>
    </div>
  );
}
