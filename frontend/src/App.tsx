import { useEffect, useMemo, useState } from "react";

import { loadSnapshot } from "./api/client";
import { ChartCard } from "./components/ChartCard";
import { BiasBanner, CompletenessStrip, DataQualityBanner } from "./components/DataQuality";
import { DistributionChart } from "./components/DistributionChart";
import { PostList } from "./components/PostList";
import { StatCards } from "./components/StatCards";
import { TimeRangeSelector } from "./components/TimeRangeSelector";
import { TimeSeriesChart } from "./components/TimeSeriesChart";
import {
  COMPOSITE,
  FIELD_LABELS,
  type Filters,
  OTHERS,
  UNKNOWN,
  applyFilters,
  approvalRate,
  availableQuarters,
  distribution,
  fieldValue,
  filterByQuarters,
  filterByRange,
  markRefiled,
  quarterSeries,
  selectVersionView,
  windowFromRange,
} from "./lib/aggregate";
import type { RunInfo, Snapshot, VersionInfo } from "./types";

interface DistConfig {
  id: string;
  title: string;
  metric: string;
  horizontal?: boolean;
}

const DIST_CONFIGS: DistConfig[] = [
  { id: "degree", title: "Degree", metric: "degree" },
  { id: "field", title: "Proposed endeavor field", metric: "field", horizontal: true },
  { id: "profession", title: "Profession", metric: "profession", horizontal: true },
  { id: "law_firm", title: "Law firm", metric: "law_firm", horizontal: true },
  { id: "premium", title: "Premium processing", metric: "premium" },
  { id: "rfe", title: "Received an RFE", metric: "rfe" },
  { id: "citations", title: "Citations", metric: "citations" },
  { id: "publications", title: "Publications", metric: "publications" },
  { id: "patents", title: "Patents", metric: "patents" },
  { id: "years_experience", title: "Years of experience", metric: "years_experience" },
  { id: "processing_days", title: "Processing time (days)", metric: "processing_days" },
];
const ALL_IDS = DIST_CONFIGS.map((c) => c.id);

function fmtDateTime(value?: number | string | null): string {
  if (!value) return "—";
  if (typeof value === "number") return new Date(value * 1000).toISOString().replace("T", " ").slice(0, 16);
  return value.replace("T", " ").replace("+00:00", " UTC");
}
function toEpoch(dateStr: string, endOfDay: boolean): number | null {
  if (!dateStr) return null;
  const ms = Date.parse(`${dateStr}T00:00:00Z`);
  if (Number.isNaN(ms)) return null;
  return Math.floor(ms / 1000) + (endOfDay ? 86_400 - 1 : 0);
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rangeKey, setRangeKey] = useState("24m");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [hide, setHide] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(ALL_IDS.map((id) => [id, true])),
  );
  const [filters, setFilters] = useState<Filters>({});
  // metric -> the top-N named labels at click time; presence means "filter to the Other tail".
  const [others, setOthers] = useState<Record<string, string[]>>({});
  const [versionKey, setVersionKey] = useState("");
  const [run, setRun] = useState<string>(COMPOSITE);
  const [quarters, setQuarters] = useState<Set<string>>(() => new Set());
  const [showQuarters, setShowQuarters] = useState(false);
  // Debug mode (model picker, version selector, completeness) is gated behind the /debug URL,
  // e.g. http://localhost:8000/debug — kept out of the way for normal viewers.
  const debug = useMemo(
    () => /(^|\/)debug\/?$/.test(typeof window !== "undefined" ? window.location.pathname : ""),
    [],
  );

  useEffect(() => {
    loadSnapshot().then(setSnapshot).catch((e) => setError(String(e)));
  }, []);

  const now = Math.floor(Date.now() / 1000);
  const [start, end] = useMemo<[number | null, number | null]>(() => {
    if (rangeKey === "custom") return [toEpoch(customStart, false), toEpoch(customEnd, true)];
    return windowFromRange(rangeKey, now);
  }, [rangeKey, customStart, customEnd, now]);

  const versions = useMemo<VersionInfo[]>(() => {
    if (!snapshot) return [];
    const meta = snapshot.meta as Record<string, unknown>;
    if (Array.isArray(meta.versions) && meta.versions.length > 0) {
      return meta.versions as VersionInfo[];
    }
    const pv = typeof meta.prompt_version === "string" ? meta.prompt_version : "";
    const sv = typeof meta.schema_version === "string" ? meta.schema_version : "";
    const runs = (Array.isArray(meta.runs) ? meta.runs : []) as RunInfo[];
    if (!pv || !sv) return [];
    return [{
      prompt_version: pv,
      schema_version: sv,
      version_key: `${pv}/${sv}`,
      runs,
      post_count: (meta.post_count as number) ?? 0,
      candidate_count: (meta.candidate_count as number) ?? 0,
      classified_count: (meta.classified_count as number) ?? 0,
      excluded_count: (meta.excluded_count as number) ?? 0,
      failed_count: (meta.failed_count as number) ?? 0,
      active_processed_count: (meta.active_processed_count as number) ?? 0,
      active_pending_count: (meta.active_pending_count as number) ?? 0,
      is_partial: Boolean(meta.is_partial),
      max_classified_at: (meta.max_classified_at as number | null) ?? null,
    }];
  }, [snapshot]);

  const activeVersionKey = useMemo(() => {
    if (!snapshot) return "";
    const meta = snapshot.meta as Record<string, unknown>;
    const pv = typeof meta.prompt_version === "string" ? meta.prompt_version : "";
    const sv = typeof meta.schema_version === "string" ? meta.schema_version : "";
    return pv && sv ? `${pv}/${sv}` : "";
  }, [snapshot]);
  const preferredVersionKey = versions.some((v) => v.version_key === activeVersionKey)
    ? activeVersionKey
    : versions[0]?.version_key ?? "";
  const selectedVersionKey = versions.some((v) => v.version_key === versionKey)
    ? versionKey
    : preferredVersionKey;
  const selectedVersion = versions.find((v) => v.version_key === selectedVersionKey) ?? null;
  const runs = selectedVersion?.runs ?? [];
  const effectiveRun = run === COMPOSITE || runs.some((r) => r.run_key === run) ? run : COMPOSITE;

  // Reduce to the selected version's run/composite, tag re-files (all-time, per author),
  // THEN apply the time window and facet filters.
  const viewRecords = useMemo(() => {
    const recs = snapshot && selectedVersionKey ? selectVersionView(snapshot.records, selectedVersionKey, effectiveRun) : [];
    return markRefiled(recs);
  }, [snapshot, selectedVersionKey, effectiveRun]);

  const quarterOptions = useMemo(() => availableQuarters(viewRecords), [viewRecords]);

  const filtered = useMemo(() => {
    // Selected quarters take precedence over the month-range window.
    const windowed = quarters.size > 0 ? filterByQuarters(viewRecords, quarters) : filterByRange(viewRecords, start, end);
    let recs = applyFilters(windowed, filters);
    // "Other" tail filters: keep records whose value isn't one of that chart's named buckets.
    for (const [metric, named] of Object.entries(others)) {
      const set = new Set(named);
      recs = recs.filter((r) => {
        const v = fieldValue(r, metric);
        return v !== UNKNOWN && !set.has(v);
      });
    }
    return recs;
  }, [viewRecords, start, end, filters, others, quarters]);

  const series = useMemo(() => quarterSeries(filtered), [filtered]);

  // Picking a month range clears any quarter selection (they're mutually exclusive).
  const onRange = (k: string) => {
    setRangeKey(k);
    setQuarters(new Set());
  };

  if (error) return <div className="wrap"><div className="center">⚠️ {error}</div></div>;
  if (!snapshot) return <div className="wrap"><div className="center">Loading…</div></div>;

  const meta = snapshot.meta as Record<string, unknown>;
  const metaNumber = (key: string) => (typeof meta[key] === "number" ? meta[key] as number : null);
  const selectedRun = effectiveRun === COMPOSITE ? null : runs.find((r) => r.run_key === effectiveRun) ?? null;
  const candidateCount = selectedVersion?.candidate_count ?? metaNumber("candidate_count") ?? 0;
  const classifiedCount = selectedRun ? selectedRun.ok : selectedVersion?.classified_count ?? metaNumber("classified_count") ?? 0;
  const excludedCount = selectedRun ? selectedRun.excluded : selectedVersion?.excluded_count ?? metaNumber("excluded_count") ?? 0;
  const failedCount = selectedRun ? selectedRun.failed : selectedVersion?.failed_count ?? metaNumber("failed_count") ?? 0;
  const processedCount = selectedRun
    ? selectedRun.ok + selectedRun.excluded + selectedRun.failed
    : selectedVersion?.active_processed_count ?? metaNumber("active_processed_count") ?? classifiedCount + excludedCount + failedCount;
  const pendingCount = selectedVersion && !selectedRun
    ? selectedVersion.active_pending_count
    : Math.max(candidateCount - processedCount, 0);
  const isPartial = candidateCount > 0 && processedCount < candidateCount;
  const viewLabel = effectiveRun === COMPOSITE ? `composite (${runs.length} run${runs.length === 1 ? "" : "s"})` : effectiveRun;
  const promptVersion = selectedVersion?.prompt_version ?? (typeof meta.prompt_version === "string" ? meta.prompt_version : "");
  const schemaVersion = selectedVersion?.schema_version ?? (typeof meta.schema_version === "string" ? meta.schema_version : "");
  const version = promptVersion ? `${promptVersion}/${schemaVersion}` : "";
  const refreshedAt = typeof meta.last_refresh === "number" || typeof meta.last_refresh === "string"
    ? meta.last_refresh
    : snapshot.generated_at;
  const setHideAll = (v: boolean) => setHide(Object.fromEntries(ALL_IDS.map((id) => [id, v])));
  const allHidden = ALL_IDS.every((id) => hide[id]);

  const toggleFilter = (field: string, label: string) =>
    setFilters((f) => (f[field] === label ? omit(f, field) : { ...f, [field]: label }));
  const setOutcome = (val: string | null) =>
    setFilters((f) => (val ? { ...f, outcome: val } : omit(f, "outcome")));
  const toggleQuarter = (q: string) =>
    setQuarters((prev) => {
      const next = new Set(prev);
      if (next.has(q)) next.delete(q);
      else next.add(q);
      return next;
    });
  const toggleOther = (metric: string, named: string[]) =>
    setOthers((prev) => {
      if (prev[metric]) {
        const { [metric]: _drop, ...rest } = prev;
        return rest;
      }
      return { ...prev, [metric]: named };
    });
  const clearFacets = () => {
    setFilters((f) => ({ ...pick(f, "outcome") }));
    setOthers({});
  };
  const facetChips: [string, string][] = [
    ...Object.entries(filters).filter(([k]) => k !== "outcome"),
    ...Object.keys(others).map((m) => [m, OTHERS] as [string, string]),
  ];

  return (
    <div className="wrap">
      <header>
        <h1>r/EB2_NIW — approval / denial data points</h1>
        <p className="sub">
          {classifiedCount.toLocaleString()} active decisions · {processedCount.toLocaleString()} /{" "}
          {candidateCount.toLocaleString()} candidates processed
          {pendingCount ? ` · ${pendingCount.toLocaleString()} pending` : ""} · refreshed{" "}
          {fmtDateTime(refreshedAt)}
          {debug ? ` · model ${viewLabel} ${version}` : ""}
        </p>
      </header>

      <BiasBanner />

      <DataQualityBanner
        backend={viewLabel}
        version={version}
        processed={processedCount}
        candidates={candidateCount}
        pending={pendingCount}
        isPartial={isPartial}
        recordCount={viewRecords.length}
      />

      <div className="controls">
        <div className="ctl-group">
          <span className="ctl-label">Time</span>
          <TimeRangeSelector
            rangeKey={rangeKey}
            onRange={onRange}
            customStart={customStart}
            customEnd={customEnd}
            onCustom={(s, e) => {
              setCustomStart(s);
              setCustomEnd(e);
            }}
            quartersActive={quarters.size > 0}
          />
          {quarterOptions.length > 1 && (
            <button
              className={quarters.size > 0 ? "seg active" : "seg"}
              onClick={() => setShowQuarters((v) => !v)}
              title="Pick specific calendar quarters"
            >
              Quarters{quarters.size > 0 ? ` · ${quarters.size}` : ""} {showQuarters ? "▴" : "▾"}
            </button>
          )}
        </div>
        {debug && versions.length > 0 && (
          <label className="range" title="Which prompt/schema version to show">
            <span className="muted" style={{ marginRight: 4 }}>Version:</span>
            <select
              className="seg"
              value={selectedVersionKey}
              onChange={(e) => {
                setVersionKey(e.target.value);
                setRun(COMPOSITE);
              }}
            >
              {versions.map((v) => (
                <option key={v.version_key} value={v.version_key}>
                  {v.version_key} ({v.classified_count} ok)
                </option>
              ))}
            </select>
          </label>
        )}
        {debug && runs.length > 0 && (
          <label className="range" title="Which classification run(s) to show">
            <span className="muted" style={{ marginRight: 4 }}>Model:</span>
            <select className="seg" value={effectiveRun} onChange={(e) => setRun(e.target.value)}>
              <option value={COMPOSITE}>Composite (majority vote · {runs.length})</option>
              {runs.map((r) => (
                <option key={r.run_key} value={r.run_key}>
                  {r.run_key} ({r.ok})
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="ctl-group">
          <span className="ctl-label">Outcome</span>
          <div className="range segmented">
            {[
              ["all", "All", null],
              ["approved", "Approved", "approved"],
              ["denied", "Denied", "denied"],
            ].map(([key, label, val]) => (
              <button
                key={key as string}
                className={(filters.outcome ?? "all") === key ? "seg active" : "seg"}
                onClick={() => setOutcome(val as string | null)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <label className="master-toggle">
          <input type="checkbox" checked={allHidden} onChange={(e) => setHideAll(e.target.checked)} />
          hide unknowns
        </label>
      </div>

      {showQuarters && quarterOptions.length > 1 && (
        <div className="chips" style={{ alignItems: "center" }}>
          <span className="muted" title="Filter by calendar quarter of the post date — overrides the range above">By quarter:</span>
          {quarterOptions.map((q) => (
            <button key={q} className={quarters.has(q) ? "seg active" : "seg"} onClick={() => toggleQuarter(q)}>
              {q.replace("-", " ")}
            </button>
          ))}
          {quarters.size > 0 && (
            <button className="chip clear" onClick={() => setQuarters(new Set())}>
              clear quarters
            </button>
          )}
        </div>
      )}

      {facetChips.length > 0 && (
        <div className="chips">
          <span className="muted">Filters:</span>
          {facetChips.map(([field, label]) => (
            <button
              key={`${field}:${label}`}
              className="chip"
              onClick={() => (label === OTHERS ? toggleOther(field, []) : setFilters((f) => omit(f, field)))}
            >
              {FIELD_LABELS[field] ?? field}: <strong>{label}</strong> ✕
            </button>
          ))}
          <button className="chip clear" onClick={clearFacets}>
            clear facets
          </button>
        </div>
      )}

      <StatCards rate={approvalRate(filtered)} />

      <p className="bias-note">
        <strong>Note:</strong> approved NIW cases tend to post on Reddit far more than denials, so this
        approval rate is biased high and likely overstates real approval odds.
      </p>

      <div className="legend" style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)", margin: "4px 2px 10px" }}>
        <span><span style={{ display: "inline-block", width: 11, height: 11, borderRadius: 3, background: "#30a46c", verticalAlign: "-1px" }} /> approved</span>
        <span><span style={{ display: "inline-block", width: 11, height: 11, borderRadius: 3, background: "#e5484d", verticalAlign: "-1px" }} /> denied</span>
        <span className="muted">click a bar to filter (incl. Unknown / Other) · bar length = volume</span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Approval over time</h3>
          <span className="muted">by quarter · reflects current filters</span>
        </div>
        <TimeSeriesChart data={series} />
      </div>

      {debug && <CompletenessStrip records={filtered} />}

      <div className="grid">
        {DIST_CONFIGS.map((c) => {
          const dist = distribution(filtered, c.metric, !!hide[c.id]);
          return (
            <ChartCard
              key={c.id}
              title={c.title}
              n={dist.n}
              unknownCount={dist.unknown_count}
              hideUnknown={!!hide[c.id]}
              onToggleHide={(v) => setHide((h) => ({ ...h, [c.id]: v }))}
            >
              <DistributionChart
                dist={dist}
                horizontal={c.horizontal}
                onSelect={(label) =>
                  label === OTHERS
                    ? toggleOther(
                        c.metric,
                        dist.buckets.filter((b) => b.label !== OTHERS && b.label !== UNKNOWN).map((b) => b.label),
                      )
                    : toggleFilter(c.metric, label)
                }
                selected={others[c.metric] ? OTHERS : filters[c.metric] ?? null}
              />
            </ChartCard>
          );
        })}
      </div>

      <PostList records={filtered} />

      <footer className="credit">
        Created by{" "}
        <a href="https://www.reddit.com/user/x_shawn" target="_blank" rel="noreferrer">u/x_shawn</a>
        {" "}· data from r/EB2_NIW via Arctic Shift
      </footer>
    </div>
  );
}

function omit(obj: Filters, key: string): Filters {
  const { [key]: _drop, ...rest } = obj;
  return rest;
}
function pick(obj: Filters, key: string): Filters {
  return key in obj ? { [key]: obj[key] } : {};
}
