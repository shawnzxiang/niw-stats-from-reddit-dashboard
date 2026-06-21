import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { APPROVED, DENIED } from "../lib/colors";
import type { ApprovalRate } from "../types";

export function StatCards({ rate }: { rate: ApprovalRate }) {
  const pct = rate.rate === null ? "—" : `${(rate.rate * 100).toFixed(1)}%`;
  const pie = [
    { name: "Approved", value: rate.approved, color: APPROVED },
    { name: "Denied", value: rate.denied, color: DENIED },
  ];
  return (
    <div className="stats">
      <div className="stat">
        <div className="stat-value">{rate.total_decided}</div>
        <div className="stat-label">decisions</div>
      </div>
      <div className="stat">
        <div className="stat-value green">{pct}</div>
        <div className="stat-label" title="Approved NIW cases tend to post on Reddit far more than denials, so this overstates real approval odds.">
          approval rate <span className="warn" style={{ cursor: "help" }}>⚠</span>
        </div>
      </div>
      <div className="stat">
        <div className="stat-value green">{rate.approved}</div>
        <div className="stat-label">approved</div>
      </div>
      <div className="stat">
        <div className="stat-value red">{rate.denied}</div>
        <div className="stat-label">denied</div>
      </div>
      <div className="stat donut">
        <ResponsiveContainer width="100%" height={90}>
          <PieChart>
            <Pie data={pie} dataKey="value" nameKey="name" innerRadius={26} outerRadius={42} paddingAngle={2}>
              {pie.map((p) => (
                <Cell key={p.name} fill={p.color} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
