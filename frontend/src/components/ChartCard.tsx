import type { ReactNode } from "react";

interface Props {
  title: string;
  n: number;
  unknownCount?: number;
  hideUnknown: boolean;
  onToggleHide: (v: boolean) => void;
  children: ReactNode;
}

export function ChartCard({ title, n, unknownCount, hideUnknown, onToggleHide, children }: Props) {
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>{title}</h3>
          <div className="muted">
            n={n}
            {unknownCount !== undefined && unknownCount > 0 ? ` · ${unknownCount} not mentioned` : ""}
          </div>
        </div>
        <label className="hide-toggle">
          <input
            type="checkbox"
            checked={hideUnknown}
            onChange={(e) => onToggleHide(e.target.checked)}
          />
          hide unknown
        </label>
      </div>
      <div className="card-body">{children}</div>
    </div>
  );
}
