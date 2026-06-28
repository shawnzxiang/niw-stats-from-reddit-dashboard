interface Props {
  rangeKey: string;
  onRange: (k: string) => void;
  customStart: string;
  customEnd: string;
  onCustom: (start: string, end: string) => void;
  quartersActive?: boolean;
}

const RANGES: [string, string][] = [
  ["3m", "3 months"],
  ["6m", "6 months"],
  ["12m", "1 year"],
  ["24m", "2 years"],
  ["36m", "3 years"],
];

export function TimeRangeSelector({ rangeKey, onRange, customStart, customEnd, onCustom, quartersActive = false }: Props) {
  // When quarters are selected they override the range, so show no range as active.
  const active = quartersActive ? "" : rangeKey;
  return (
    <div className="range segmented">
      {RANGES.map(([k, label]) => (
        <button key={k} className={active === k ? "seg active" : "seg"} onClick={() => onRange(k)}>
          {label}
        </button>
      ))}
      <button className={active === "custom" ? "seg active" : "seg"} onClick={() => onRange("custom")}>
        Custom
      </button>
      {rangeKey === "custom" && (
        <span className="custom-dates">
          <input type="date" value={customStart} onChange={(e) => onCustom(e.target.value, customEnd)} />
          <span>→</span>
          <input type="date" value={customEnd} onChange={(e) => onCustom(customStart, e.target.value)} />
        </span>
      )}
    </div>
  );
}
