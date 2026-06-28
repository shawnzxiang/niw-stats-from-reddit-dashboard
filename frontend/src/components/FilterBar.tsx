import { useEffect, useMemo, useRef, useState } from "react";

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
  /** Toggle a single value within a metric's selection (multi-select). */
  onToggle: (metric: string, value: string) => void;
  /** Clear every selected value for a metric. */
  onClearMetric: (metric: string) => void;
  onClear: () => void;
}

export function FilterBar({ records, filters, onToggle, onClearMetric, onClear }: Props) {
  const options = useMemo(
    () => Object.fromEntries(FILTER_METRICS.map((m) => [m, distinctValues(records, m)])),
    [records],
  );
  // Total number of selected values across all metrics (one filter chip each).
  const activeCount = FILTER_METRICS.reduce((n, m) => n + (filters[m]?.length ?? 0), 0);

  // Only one dropdown menu is open at a time; close on outside click / Escape.
  const [open, setOpen] = useState<string | null>(null);
  const barRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (barRef.current && !barRef.current.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const summary = (m: string) => {
    const sel = filters[m] ?? [];
    if (sel.length === 0) return "All";
    if (sel.length === 1) return sel[0];
    return `${sel.length} selected`;
  };

  return (
    <div className="filter-bar" ref={barRef}>
      <span className="filter-bar-label">Filter by</span>
      {FILTER_METRICS.map((m) => {
        const sel = filters[m] ?? [];
        return (
          <div key={m} className="filter-select">
            <span>{FIELD_LABELS[m] ?? m}</span>
            <button
              type="button"
              className={sel.length ? "seg ms-trigger active" : "seg ms-trigger"}
              onClick={() => setOpen((o) => (o === m ? null : m))}
              aria-expanded={open === m}
              aria-haspopup="listbox"
              title={sel.length > 1 ? sel.join(", ") : undefined}
            >
              <span className="ms-summary">{summary(m)}</span>
              <span className="ms-caret">▾</span>
            </button>
            {open === m && (
              <div className="ms-menu" role="listbox" aria-multiselectable="true">
                {sel.length > 0 && (
                  <button type="button" className="ms-clear" onClick={() => onClearMetric(m)}>
                    Clear selection
                  </button>
                )}
                {options[m].map((o) => (
                  <label key={o} className="ms-option">
                    <input
                      type="checkbox"
                      checked={sel.includes(o)}
                      onChange={() => onToggle(m, o)}
                    />
                    <span>{o}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {activeCount > 0 && (
        <button className="chip clear filter-clear" onClick={onClear}>
          clear {activeCount} filter{activeCount > 1 ? "s" : ""} ✕
        </button>
      )}
    </div>
  );
}
