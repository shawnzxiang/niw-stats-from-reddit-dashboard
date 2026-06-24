import type { KnownPair, SlimRecord } from "../types";

function num(pair: KnownPair | undefined): string {
  if (!pair) return "";
  const [v, known] = pair;
  return known && v !== null ? String(v) : "";
}

// CSV columns for the public dataset — one row per decision. [value, known] pairs are flattened
// to the value (blank when "not mentioned"); permalink becomes a full Reddit URL.
const COLUMNS: [string, (r: SlimRecord) => string][] = [
  ["date", (r) => new Date(r.created_utc * 1000).toISOString().slice(0, 10)],
  ["outcome", (r) => r.outcome ?? ""],
  ["degree", (r) => r.degree ?? ""],
  ["field", (r) => r.field ?? ""],
  ["profession", (r) => r.profession ?? ""],
  ["law_firm", (r) => r.law_firm ?? ""],
  ["citations", (r) => num(r.citations)],
  ["publications", (r) => num(r.publications)],
  ["patents", (r) => num(r.patents)],
  ["years_experience", (r) => num(r.years_experience)],
  ["processing_days", (r) => num(r.processing_days)],
  ["premium_processing", (r) => (r.premium_processing == null ? "" : r.premium_processing ? "Premium" : "Regular")],
  ["rfe", (r) => (r.was_rfed == null ? "" : r.was_rfed ? "Yes" : "No")],
  ["rfe_date", (r) => r.rfe_date ?? ""],
  ["rfe_response_date", (r) => r.rfe_response_date ?? ""],
  ["refiled", (r) => (r.refiled ? "Yes" : "")],
  ["reddit_url", (r) => (r.permalink ? `https://www.reddit.com${r.permalink}` : "")],
  ["title", (r) => r.title ?? ""],
];

/** RFC-4180 field escaping: wrap in quotes and double any embedded quotes when needed. */
function esc(s: string): string {
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCSV(records: SlimRecord[]): string {
  const header = COLUMNS.map(([h]) => h).join(",");
  const rows = records.map((r) => COLUMNS.map(([, f]) => esc(f(r))).join(","));
  return [header, ...rows].join("\r\n");
}

export function downloadCsv(filename: string, csv: string): void {
  // Lead with a UTF-8 BOM so Excel renders accented names correctly.
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
