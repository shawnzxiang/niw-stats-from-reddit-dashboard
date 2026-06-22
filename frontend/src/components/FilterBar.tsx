import { useMemo } from "react";

import { FIELD_LABELS, type Filters, distinctValues } from "../lib/aggregate";
import type { SlimRecord } from "../types";

// The dimensions offered as dropdown filters (outcome + time live in the controls row above).
const FILTER_METRICS = [
  "degree",
  "field",
  "profession",
  "law_firm",
  "citations",
  "publications",
  "patents",
  "years_experience",
  "processing_days",
  "premium",
  "rfe",
];

interface Props {
  /** Source for the option lists — pre-facet records, so options stay stable as you filter. */
  records: SlimRecord[];
  filters: Filters;
  onChange: (metric: string, value: string | null) => void;
  onClear: () => void;
}

export function FilterBar({ records, filters, onChange, onClear }: Props) {
  const options = useMemo(
    () => Object.fromEntries(FILTER_METRICS.map((m) => [m, distinctValues(records, m)])),
    [records],
  );
  const activeCount = FILTER_METRICS.filter((m) => filters[m]).length;

  return (
    <div className="filter-bar">
      <span className="filter-bar-label">Filter by</span>
      {FILTER_METRICS.map((m) => (
        <label key={m} className="filter-select">
          <span>{FIELD_LABELS[m] ?? m}</span>
          <select
            className="seg"
            value={filters[m] ?? ""}
            onChange={(e) => onChange(m, e.target.value || null)}
          >
            <option value="">All</option>
            {options[m].map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      ))}
      {activeCount > 0 && (
        <button className="chip clear filter-clear" onClick={onClear}>
          clear {activeCount} filter{activeCount > 1 ? "s" : ""} ✕
        </button>
      )}
    </div>
  );
}
