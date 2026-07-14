import { useEffect, useState } from "react";
import { Boxes } from "lucide-react";
import { api, StrategyInfo } from "../api";

export default function StrategyPanel() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);

  useEffect(() => {
    api.strategies().then(setStrategies);
  }, []);

  return (
    <div>
      <h2 className="section-title">策略管理</h2>
      <p className="section-desc">
        已注册的策略及其可调参数。参数用于单次回测与场景矩阵的网格寻优。
      </p>
      {strategies.map((s) => (
        <div className="card" key={s.key}>
          <div className="toolbar">
            <Boxes size={16} />
            <strong>{s.name}</strong>
            <span className="muted small mono">({s.key})</span>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            {s.description}
          </p>
          <table>
            <thead>
              <tr>
                <th>参数</th>
                <th className="num">默认</th>
                <th className="num">最小</th>
                <th className="num">最大</th>
                <th className="num">步长</th>
              </tr>
            </thead>
            <tbody>
              {s.params.map((p) => (
                <tr key={p.name}>
                  <td className="mono">{p.name}</td>
                  <td className="num mono">{p.default}</td>
                  <td className="num mono">{p.min}</td>
                  <td className="num mono">{p.max}</td>
                  <td className="num mono">{p.step}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
