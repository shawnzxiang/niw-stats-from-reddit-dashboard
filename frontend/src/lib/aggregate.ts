// Faithful TypeScript port of niw_stats/stats/aggregate.py.
// Kept in lockstep with the Python reference via the parity fixture test.

import type {
  ApprovalByGroup,
  ApprovalRate,
  Distribution,
  GroupRow,
  KnownPair,
  SlimRecord,
} from "../types";

type Bin = [string, number, number | null]; // label, lower-inclusive, upper-exclusive|null

export const PUBLICATION_BINS: Bin[] = [
  ["0", 0, 1], ["1–2", 1, 3], ["3–5", 3, 6], ["6–10", 6, 11], ["11–20", 11, 21], ["21+", 21, null],
];
export const PATENT_BINS: Bin[] = [
  ["0", 0, 1], ["1", 1, 2], ["2–3", 2, 4], ["4+", 4, null],
];
export const CITATION_BINS: Bin[] = [
  ["0", 0, 1], ["1–10", 1, 11], ["11–20", 11, 21], ["21–30", 21, 31],
  ["31–50", 31, 51], ["51–100", 51, 101], ["101–200", 101, 201],
  ["201–500", 201, 501], ["501+", 501, null],
];
export const YEARS_BINS: Bin[] = [
  ["0–2", 0, 3], ["3–5", 3, 6], ["6–10", 6, 11], ["11–15", 11, 16], ["16+", 16, null],
];
export const DURATION_BINS: Bin[] = [
  ["0–30", 0, 31], ["31–60", 31, 61], ["61–90", 61, 91], ["91–120", 91, 121],
  ["121–180", 121, 181], ["181–365", 181, 366], ["365+", 366, null],
];

export const UNKNOWN = "Unknown";
const DAY = 86_400;
export const RANGE_DAYS: Record<string, number> = { "3m": 90, "6m": 180, "12m": 365, "24m": 730 };

function premiumLabel(v: boolean | null): string | null {
  return v == null ? null : v ? "Premium" : "Regular";
}
function rfeLabel(v: boolean | null): string | null {
  return v == null ? null : v ? "RFE'd" : "No RFE";
}
function knownPair(pair: KnownPair | undefined): KnownPair {
  return pair ?? [null, false];
}

const CATEGORICAL: Record<string, (r: SlimRecord) => string | null> = {
  outcome: (r) => r.outcome,
  degree: (r) => r.degree,
  field: (r) => r.field,
  profession: (r) => r.profession ?? null,
  law_firm: (r) => r.law_firm,
  premium: (r) => premiumLabel(r.premium_processing),
  rfe: (r) => rfeLabel(r.was_rfed),
};
const NUMERIC: Record<string, { get: (r: SlimRecord) => KnownPair; bins: Bin[]; kind: "numeric" | "duration" }> = {
  publications: { get: (r) => r.publications, bins: PUBLICATION_BINS, kind: "numeric" },
  patents: { get: (r) => knownPair(r.patents), bins: PATENT_BINS, kind: "numeric" },
  citations: { get: (r) => r.citations, bins: CITATION_BINS, kind: "numeric" },
  years_experience: { get: (r) => r.years_experience, bins: YEARS_BINS, kind: "numeric" },
  processing_days: { get: (r) => r.processing_days, bins: DURATION_BINS, kind: "duration" },
};

export const METRICS = [...Object.keys(CATEGORICAL), ...Object.keys(NUMERIC)];

function bucketLabel(value: number, bins: Bin[]): string {
  for (const [label, lo, hi] of bins) {
    if (value >= lo && (hi === null || value < hi)) return label;
  }
  return bins[bins.length - 1][0];
}

export function windowFromRange(rangeKey: string, now: number): [number, number] {
  return [now - RANGE_DAYS[rangeKey] * DAY, now];
}

// --- run selection / composite voting (port of aggregate.select_view) -------

export const COMPOSITE = "composite";

export function versionKeyOf(promptVersion: string | null | undefined, schemaVersion: string | null | undefined): string {
  return `${promptVersion ?? ""}/${schemaVersion ?? ""}`;
}

export function filterByVersion(records: SlimRecord[], versionKey: string): SlimRecord[] {
  return records.filter((r) => {
    if (!r.prompt_version && !r.schema_version) return true;
    return versionKeyOf(r.prompt_version, r.schema_version) === versionKey;
  });
}

function recency(r: SlimRecord): number {
  return r.classified_at ?? 0;
}

function vote(group: SlimRecord[]): SlimRecord {
  if (group.length === 1) return group[0];
  const tally = new Map<string | null, number>();
  for (const r of group) tally.set(r.outcome, (tally.get(r.outcome) ?? 0) + 1);
  let bestOutcome: string | null = null;
  let bestCount = -1;
  let bestRecency = -1;
  for (const [outcome, count] of tally) {
    const rec = Math.max(0, ...group.filter((r) => r.outcome === outcome).map(recency));
    if (count > bestCount || (count === bestCount && rec > bestRecency)) {
      bestOutcome = outcome;
      bestCount = count;
      bestRecency = rec;
    }
  }
  const winners = group.filter((r) => r.outcome === bestOutcome);
  return winners.reduce((a, b) => (recency(b) > recency(a) ? b : a));
}

/** Reduce multi-run records to the dashboard view: composite vote, or a single run. */
export function selectView(records: SlimRecord[], run: string = COMPOSITE): SlimRecord[] {
  let chosen: SlimRecord[];
  if (run && run !== COMPOSITE) {
    chosen = records.filter((r) => r.run === run);
  } else {
    const byPost = new Map<string | null, SlimRecord[]>();
    for (const r of records) {
      const key = r.id ?? null;
      const arr = byPost.get(key);
      if (arr) arr.push(r);
      else byPost.set(key, [r]);
    }
    chosen = [...byPost.values()].map(vote);
  }
  return chosen
    .slice()
    .sort((a, b) => (b.created_utc ?? 0) - (a.created_utc ?? 0) || (a.id ?? "").localeCompare(b.id ?? ""));
}

export function selectVersionView(records: SlimRecord[], versionKey: string, run: string = COMPOSITE): SlimRecord[] {
  return selectView(filterByVersion(records, versionKey), run);
}

// --- re-file detection (port of aggregate.mark_refiled) ---------------------

const AUTHOR_SKIP = new Set(["", "[deleted]", "[removed]", "AutoModerator"]);

/** Flag denied cases whose author was later approved (a re-file), from records alone. */
export function markRefiled(records: SlimRecord[]): SlimRecord[] {
  // The public snapshot strips `author` and ships server-computed refiled/refiled_url instead.
  // Without usernames we can't (and shouldn't) recompute — preserve the server flags as-is.
  const hasAuthors = records.some((r) => r.author && !AUTHOR_SKIP.has(r.author));
  if (!hasAuthors) return records;
  for (const r of records) {
    r.refiled = null;
    r.refiled_url = null;
    r.refile_approval = null;
  }
  const byAuthor = new Map<string, SlimRecord[]>();
  for (const r of records) {
    const a = r.author;
    if (!a || AUTHOR_SKIP.has(a)) continue;
    const arr = byAuthor.get(a);
    if (arr) arr.push(r);
    else byAuthor.set(a, [r]);
  }
  for (const recs of byAuthor.values()) {
    const approved = recs.filter((r) => r.outcome === "approved");
    if (!approved.length) continue;
    for (const d of recs.filter((r) => r.outcome === "denied")) {
      const later = approved.filter((a) => (a.created_utc ?? 0) > (d.created_utc ?? 0));
      if (later.length) {
        const first = later.reduce((m, a) => ((a.created_utc ?? 0) < (m.created_utc ?? 0) ? a : m));
        d.refiled = true;
        d.refiled_url = first.permalink ?? null;
        first.refile_approval = true;
      }
    }
  }
  return records;
}

export function filterByRange(
  records: SlimRecord[],
  start: number | null,
  end: number | null,
): SlimRecord[] {
  return records.filter(
    (r) => (start === null || r.created_utc >= start) && (end === null || r.created_utc <= end),
  );
}

// --- year/quarter filtering (post date) -------------------------------------

export function quarterKey(epoch: number): string {
  const d = new Date(epoch * 1000);
  return `${d.getUTCFullYear()}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
}

/** Distinct quarter keys present in the records, newest first (e.g. "2026-Q2"). */
export function availableQuarters(records: SlimRecord[]): string[] {
  const seen = new Set<string>();
  for (const r of records) seen.add(quarterKey(r.created_utc));
  return [...seen].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
}

export function filterByQuarters(records: SlimRecord[], keys: Set<string>): SlimRecord[] {
  if (keys.size === 0) return records;
  return records.filter((r) => keys.has(quarterKey(r.created_utc)));
}

export interface QuarterPoint {
  quarter: string;
  approved: number;
  denied: number;
  rate: number | null;
}

/** Approved/denied counts + approval rate per calendar quarter, chronological. */
export function quarterSeries(records: SlimRecord[]): QuarterPoint[] {
  const m = new Map<string, { approved: number; denied: number }>();
  for (const r of records) {
    const q = quarterKey(r.created_utc);
    let s = m.get(q);
    if (!s) {
      s = { approved: 0, denied: 0 };
      m.set(q, s);
    }
    if (r.outcome === "approved") s.approved += 1;
    else if (r.outcome === "denied") s.denied += 1;
  }
  return [...m.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([quarter, s]) => ({
      quarter,
      approved: s.approved,
      denied: s.denied,
      rate: s.approved + s.denied ? s.approved / (s.approved + s.denied) : null,
    }));
}

type Slot = { count: number; approved: number; denied: number };
function newSlot(): Slot {
  return { count: 0, approved: 0, denied: 0 };
}
function tally(s: Slot, r: SlimRecord): void {
  s.count += 1;
  if (r.outcome === "approved") s.approved += 1;
  else if (r.outcome === "denied") s.denied += 1;
}
function bucketOf(label: string, s: Slot) {
  return { label, count: s.count, approved: s.approved, denied: s.denied };
}

export const OTHERS = "Other";
const MAX_CATEGORIES = 9;

type Bucket3 = { label: string; count: number; approved: number; denied: number };

function collapseOthers(buckets: Bucket3[]): Bucket3[] {
  const named = buckets.filter((b) => b.label !== OTHERS).sort((a, b) => b.count - a.count);
  const existing = buckets.find((b) => b.label === OTHERS) ?? null;
  if (named.length + (existing ? 1 : 0) <= MAX_CATEGORIES) {
    return existing ? [...named, existing] : named;
  }
  const keep = named.slice(0, MAX_CATEGORIES);
  const tail = named.slice(MAX_CATEGORIES);
  const other: Bucket3 = { label: OTHERS, count: 0, approved: 0, denied: 0 };
  for (const b of existing ? [...tail, existing] : tail) {
    other.count += b.count;
    other.approved += b.approved;
    other.denied += b.denied;
  }
  return [...keep, other];
}

function categorical(records: SlimRecord[], accessor: (r: SlimRecord) => string | null, hideUnknown: boolean) {
  const counts = new Map<string, Slot>();
  const unknown = newSlot();
  for (const r of records) {
    const v = accessor(r);
    if (v === null || v === undefined) {
      tally(unknown, r);
    } else {
      let s = counts.get(v);
      if (!s) {
        s = newSlot();
        counts.set(v, s);
      }
      tally(s, r);
    }
  }
  const buckets = collapseOthers([...counts.entries()].map(([label, s]) => bucketOf(label, s)));
  if (!hideUnknown && unknown.count) buckets.push(bucketOf(UNKNOWN, unknown));
  const nKnown = buckets.filter((b) => b.label !== UNKNOWN).reduce((s, b) => s + b.count, 0);
  return { kind: "categorical" as const, buckets, unknown_count: unknown.count, n: nKnown, total: records.length };
}

function numeric(
  records: SlimRecord[],
  get: (r: SlimRecord) => KnownPair,
  bins: Bin[],
  hideUnknown: boolean,
  kind: "numeric" | "duration",
) {
  const counts = new Map<string, Slot>(bins.map((b) => [b[0], newSlot()]));
  const unknown = newSlot();
  for (const r of records) {
    const [value, known] = get(r);
    if (!known || value === null) tally(unknown, r);
    else tally(counts.get(bucketLabel(value, bins))!, r);
  }
  const buckets = bins.map(([label]) => bucketOf(label, counts.get(label)!));
  if (!hideUnknown && unknown.count) buckets.push(bucketOf(UNKNOWN, unknown));
  const n = bins.reduce((s, [label]) => s + (counts.get(label)?.count ?? 0), 0);
  return { kind, buckets, unknown_count: unknown.count, n, total: records.length };
}

export function distribution(records: SlimRecord[], metric: string, hideUnknown = false): Distribution {
  if (metric in CATEGORICAL) {
    return { metric, ...categorical(records, CATEGORICAL[metric], hideUnknown) };
  }
  if (metric in NUMERIC) {
    const { get, bins, kind } = NUMERIC[metric];
    return { metric, ...numeric(records, get, bins, hideUnknown, kind) };
  }
  throw new Error(`unknown metric: ${metric}`);
}

export function approvalRate(records: SlimRecord[]): ApprovalRate {
  const approved = records.filter((r) => r.outcome === "approved").length;
  const denied = records.filter((r) => r.outcome === "denied").length;
  const decided = approved + denied;
  return { approved, denied, total_decided: decided, rate: decided ? approved / decided : null };
}

function groupLabel(r: SlimRecord, group: string): string {
  if (group === "degree") return r.degree ?? UNKNOWN;
  if (group === "field") return r.field ?? UNKNOWN;
  if (group === "law_firm") return r.law_firm ?? UNKNOWN;
  if (group === "premium") return premiumLabel(r.premium_processing) ?? UNKNOWN;
  if (group === "rfe") return rfeLabel(r.was_rfed) ?? UNKNOWN;
  if (group === "citation_bucket") {
    const [value, known] = r.citations;
    return known && value !== null ? bucketLabel(value, CITATION_BINS) : UNKNOWN;
  }
  throw new Error(`unknown group: ${group}`);
}

export function approvalRateByGroup(records: SlimRecord[], group: string, hideUnknown = false): ApprovalByGroup {
  const agg = new Map<string, { approved: number; denied: number }>();
  for (const r of records) {
    if (r.outcome !== "approved" && r.outcome !== "denied") continue;
    const label = groupLabel(r, group);
    const slot = agg.get(label) ?? { approved: 0, denied: 0 };
    slot[r.outcome] += 1;
    agg.set(label, slot);
  }
  let rows: GroupRow[] = [...agg.entries()]
    .filter(([label]) => !(hideUnknown && label === UNKNOWN))
    .map(([label, c]) => {
      const n = c.approved + c.denied;
      return { label, approved: c.approved, denied: c.denied, n, rate: n ? c.approved / n : null };
    });

  if (group === "citation_bucket") {
    const order = new Map<string, number>(CITATION_BINS.map((b, i) => [b[0], i]));
    order.set(UNKNOWN, order.size);
    rows = rows.sort((a, b) => (order.get(a.label) ?? 99) - (order.get(b.label) ?? 99));
  } else {
    rows = rows.sort((a, b) => {
      const au = a.label === UNKNOWN ? 1 : 0;
      const bu = b.label === UNKNOWN ? 1 : 0;
      return au - bu || b.n - a.n;
    });
  }
  return { group, groups: rows };
}

export function summary(records: SlimRecord[]) {
  return { total: records.length, ...approvalRate(records) };
}

// --- drill-down filtering ---------------------------------------------------
// A filter maps a field key (outcome/degree/field/law_firm or a numeric metric) to the set
// of labels that may match (categorical values or numeric bucket labels). Multiple values for
// one field are OR'd; different fields are AND'd. An empty list means "no constraint".
export type Filters = Record<string, string[]>;

export function bucketLabelFor(metric: string, record: SlimRecord): string {
  const num = NUMERIC[metric];
  if (!num) return UNKNOWN;
  const [v, known] = num.get(record);
  return known && v !== null ? bucketLabel(v, num.bins) : UNKNOWN;
}

export function fieldValue(record: SlimRecord, field: string): string {
  if (field in CATEGORICAL) return CATEGORICAL[field](record) ?? UNKNOWN;
  if (field in NUMERIC) return bucketLabelFor(field, record);
  return UNKNOWN;
}

export function recordMatchesFilters(record: SlimRecord, filters: Filters): boolean {
  return Object.entries(filters).every(
    ([field, labels]) => labels.length === 0 || labels.includes(fieldValue(record, field)),
  );
}

export function applyFilters(records: SlimRecord[], filters: Filters): SlimRecord[] {
  if (!Object.values(filters).some((labels) => labels.length > 0)) return records;
  return records.filter((r) => recordMatchesFilters(r, filters));
}

/** Distinct filter values for a metric — the options for a filter dropdown.
 *  Numeric metrics are ordered by bin; categorical by frequency; Unknown always last. */
export function distinctValues(records: SlimRecord[], metric: string): string[] {
  const counts = new Map<string, number>();
  for (const r of records) {
    const v = fieldValue(r, metric);
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  const entries = [...counts.entries()];
  const num = NUMERIC[metric];
  if (num) {
    const order = new Map(num.bins.map((b, i) => [b[0], i] as const));
    const rank = (l: string) => (l === UNKNOWN ? 1e6 : order.get(l) ?? 1e5);
    entries.sort((a, b) => rank(a[0]) - rank(b[0]));
  } else {
    const unk = (l: string) => (l === UNKNOWN ? 1 : 0);
    entries.sort((a, b) => unk(a[0]) - unk(b[0]) || b[1] - a[1]);
  }
  return entries.map(([label]) => label);
}

// Human-readable label for a filter field (for chips).
export const FIELD_LABELS: Record<string, string> = {
  outcome: "Outcome",
  degree: "Degree",
  field: "Field",
  profession: "Profession",
  law_firm: "Law firm",
  citations: "Citations",
  publications: "Publications",
  patents: "Patents",
  years_experience: "Years exp.",
  processing_days: "Processing days",
  premium: "Premium processing",
  rfe: "RFE",
};
