import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { APPROVED, DENIED, RATE } from "../lib/colors";
import type { QuarterPoint } from "../lib/aggregate";

const AXIS = "#86868b";

function fmtQ(q: string): string {
  return q.replace("-", " ");
}

function SeriesTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { payload: QuarterPoint }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: "var(--card)", border: "0.5px solid rgba(0,0,0,0.18)", borderRadius: 8, padding: "7px 10px", fontSize: 12, color: "var(--ink)" }}>
      <div style={{ fontWeight: 500, marginBottom: 3 }}>{fmtQ(label ?? "")}</div>
      <div style={{ color: APPROVED }}>approved {d.approved}</div>
      <div style={{ color: DENIED }}>denied {d.denied}</div>
      {d.rate != null && <div style={{ marginTop: 3, color: RATE }}>approval {Math.round(d.rate * 100)}%</div>}
    </div>
  );
}

export function TimeSeriesChart({ data }: { data: QuarterPoint[] }) {
  if (data.length === 0) {
    return <div className="center">no data in range</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ left: 0, right: 4, top: 16, bottom: 8 }}>
        <CartesianGrid vertical={false} stroke="rgba(0,0,0,0.06)" />
        <XAxis dataKey="quarter" tickFormatter={fmtQ} tick={{ fontSize: 11, fill: AXIS }} axisLine={false} tickLine={false} />
        <YAxis yAxisId="count" allowDecimals={false} width={34} tick={{ fontSize: 11, fill: AXIS }} axisLine={false} tickLine={false} />
        <YAxis
          yAxisId="rate"
          orientation="right"
          domain={[0, 1]}
          width={42}
          tickFormatter={(v) => `${Math.round(v * 100)}%`}
          tick={{ fontSize: 11, fill: RATE }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip content={<SeriesTooltip />} cursor={{ fill: "rgba(0,0,0,0.035)" }} />
        <Bar yAxisId="count" dataKey="approved" stackId="o" fill={APPROVED} isAnimationActive={false} />
        <Bar yAxisId="count" dataKey="denied" stackId="o" fill={DENIED} isAnimationActive={false} />
        <Line
          yAxisId="rate"
          type="monotone"
          dataKey="rate"
          name="approval rate"
          stroke={RATE}
          strokeWidth={2}
          dot={{ r: 3, fill: RATE }}
          isAnimationActive={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
