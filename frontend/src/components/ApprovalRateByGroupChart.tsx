import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ApprovalByGroup, GroupRow } from "../types";

function RateTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: GroupRow }> }) {
  if (!active || !payload || payload.length === 0) return null;
  const r = payload[0].payload;
  const pct = r.rate === null ? "—" : `${(r.rate * 100).toFixed(0)}%`;
  return (
    <div style={{ background: "#fff", border: "1px solid var(--line)", borderRadius: 8, padding: "6px 10px", fontSize: 12 }}>
      <strong>{r.label}</strong>
      <div>approval rate: {pct}</div>
      <div>{r.approved} approved · {r.denied} denied (n={r.n})</div>
    </div>
  );
}

export function ApprovalRateByGroupChart({
  data,
  onSelect,
}: {
  data: ApprovalByGroup;
  onSelect?: (label: string) => void;
}) {
  const rows = data.groups;
  if (rows.length === 0) return <div className="center">no decisions in range</div>;
  const chartClick = onSelect
    ? (state: { activeLabel?: string } | null) => {
        if (state?.activeLabel) onSelect(state.activeLabel);
      }
    : undefined;
  const cursor = onSelect ? "pointer" : "default";
  return (
    <>
      <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 38)}>
        <BarChart data={rows} layout="vertical" margin={{ left: 12, right: 16, top: 4, bottom: 4 }} onClick={chartClick}>
          <XAxis type="number" allowDecimals={false} />
          <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 12 }} />
          <Tooltip content={<RateTooltip />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
          <Bar dataKey="approved" stackId="a" fill="var(--green)" style={{ cursor }} />
          <Bar dataKey="denied" stackId="a" fill="var(--red)" radius={[0, 3, 3, 0]} style={{ cursor }} />
        </BarChart>
      </ResponsiveContainer>
      <div className="legend">
        <span><i style={{ background: "var(--green)" }} />approved</span>
        <span><i style={{ background: "var(--red)" }} />denied</span>
        <span className="muted">hover for approval rate</span>
      </div>
    </>
  );
}
