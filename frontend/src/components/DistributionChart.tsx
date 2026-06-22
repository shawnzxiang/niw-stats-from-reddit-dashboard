import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { APPROVED, DENIED, NEUTRAL } from "../lib/colors";
import type { Distribution } from "../types";

interface Props {
  dist: Distribution;
  horizontal?: boolean;
  color?: string;
  onSelect?: (label: string) => void;
  selected?: string | null;
}

const GREEN = APPROVED;
const RED = DENIED;
const GRAY = NEUTRAL;
const AXIS = "#86868b";

interface Row {
  label: string;
  count: number;
  approved: number;
  denied: number;
  other: number;
  rate: number | null;
}

function rateText(v: number | null | undefined): string {
  return v == null ? "" : `${Math.round(v * 100)}%`;
}

function RateTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { payload: Row }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const decided = d.approved + d.denied;
  return (
    <div style={{ background: "var(--card, #fff)", border: "0.5px solid rgba(0,0,0,0.18)", borderRadius: 6, padding: "6px 9px", fontSize: 12, color: "var(--ink)" }}>
      <div style={{ fontWeight: 500, marginBottom: 3 }}>{label}</div>
      <div style={{ color: GREEN }}>approved {d.approved}</div>
      <div style={{ color: RED }}>denied {d.denied}</div>
      {decided > 0 && <div style={{ marginTop: 3 }}>approval {Math.round((d.approved / decided) * 100)}% · n={decided}</div>}
    </div>
  );
}

// Bars are split by outcome: approved (green) + denied (red) + outcome-unknown (gray),
// stacked so the total length is the volume; the approval rate is labelled at each bar's end.
export function DistributionChart({ dist, horizontal = false, onSelect }: Props) {
  const data: Row[] = dist.buckets.map((b) => {
    const decided = b.approved + b.denied;
    return {
      ...b,
      other: Math.max(0, b.count - b.approved - b.denied),
      rate: decided ? b.approved / decided : null,
    };
  });
  const chartClick = onSelect
    ? (state: { activeLabel?: string } | null) => {
        if (state?.activeLabel) onSelect(state.activeLabel);
      }
    : undefined;
  const cursor = onSelect ? "pointer" : "default";

  if (data.length === 0) {
    return <div className="center">no data in range</div>;
  }

  // The end-of-bar number is the approval rate. Render it in the "approved" green and bold so it
  // reads as "% approved" rather than a share of the bar's length (which is volume). See the legend.
  const rateLabel = (
    <LabelList
      dataKey="rate"
      position={horizontal ? "right" : "top"}
      formatter={rateText}
      fontSize={10}
      fontWeight={700}
      fill={GREEN}
    />
  );

  if (horizontal) {
    return (
      <ResponsiveContainer width="100%" height={Math.max(160, data.length * 30)}>
        <BarChart data={data} layout="vertical" margin={{ left: 12, right: 40, top: 4, bottom: 4 }} onClick={chartClick}>
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: AXIS }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="label" width={130} tick={{ fontSize: 12, fill: AXIS }} axisLine={false} tickLine={false} />
          <Tooltip content={<RateTooltip />} cursor={{ fill: "rgba(0,0,0,0.035)" }} />
          <Bar dataKey="approved" stackId="o" fill={GREEN} style={{ cursor }} isAnimationActive={false} />
          <Bar dataKey="denied" stackId="o" fill={RED} style={{ cursor }} isAnimationActive={false} />
          <Bar dataKey="other" stackId="o" fill={GRAY} style={{ cursor }} isAnimationActive={false}>
            {rateLabel}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  const many = data.length > 6;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ left: 0, right: 8, top: 18, bottom: many ? 40 : 8 }} onClick={chartClick}>
        <XAxis
          dataKey="label"
          tick={{ fontSize: 11, fill: AXIS }}
          axisLine={false}
          tickLine={false}
          interval={0}
          angle={many ? -30 : 0}
          textAnchor={many ? "end" : "middle"}
          height={many ? 54 : 24}
        />
        <YAxis allowDecimals={false} width={32} tick={{ fontSize: 11, fill: AXIS }} axisLine={false} tickLine={false} />
        <Tooltip content={<RateTooltip />} cursor={{ fill: "rgba(0,0,0,0.035)" }} />
        <Bar dataKey="approved" stackId="o" fill={GREEN} style={{ cursor }} isAnimationActive={false} />
        <Bar dataKey="denied" stackId="o" fill={RED} style={{ cursor }} isAnimationActive={false} />
        <Bar dataKey="other" stackId="o" fill={GRAY} style={{ cursor }} isAnimationActive={false}>
          {rateLabel}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
