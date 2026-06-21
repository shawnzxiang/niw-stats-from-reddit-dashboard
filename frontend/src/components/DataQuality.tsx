import { useState } from "react";

import type { SlimRecord } from "../types";

/**
 * Always-on framing banner: the whole dataset is directional, not authoritative.
 * Dismissible (persisted) so repeat visitors aren't nagged, but shown by default.
 */
export function BiasBanner() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem("niw_bias_dismissed") === "1";
    } catch {
      return false;
    }
  });
  if (dismissed) return null;
  const dismiss = () => {
    try {
      localStorage.setItem("niw_bias_dismissed", "1");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  };
  return (
    <div className="bias-banner" role="note">
      <span className="bias-banner-icon" aria-hidden>
        ◐
      </span>
      <div className="bias-banner-body">
        <strong>Directional, not definitive — read these as signals, not statistics.</strong>
        <p>
          Every data point is <b>self-reported on Reddit and unverified</b>. Approved cases get shared far
          more than denials, so the approval rate here is <b>biased high</b>. The sample is small and
          self-selected — use it to get a feel for <i>what kinds of profiles file and how they tend to fare</i>,
          not to predict your own odds or to stand in for official USCIS numbers.
        </p>
      </div>
      <button className="bias-banner-x" onClick={dismiss} aria-label="Dismiss notice" title="Dismiss">
        ✕
      </button>
    </div>
  );
}

interface BannerProps {
  backend: string;
  version: string;
  processed: number;
  candidates: number;
  pending: number;
  isPartial: boolean;
  recordCount: number;
}

interface CompletenessItem {
  key: string;
  label: string;
  known: number;
  total: number;
  rate: number | null;
}

function pct(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

export function DataQualityBanner({
  backend,
  version,
  processed,
  candidates,
  pending,
  isPartial,
  recordCount,
}: BannerProps) {
  if (!isPartial && recordCount > 0) return null;

  const text = recordCount === 0
    ? `${backend} ${version} has no active decisions yet.`
    : `${backend} ${version} is ${processed.toLocaleString()} / ${candidates.toLocaleString()} candidates processed.`;

  return (
    <div className="quality-banner" role="status">
      <strong>Preliminary dataset.</strong>{" "}
      {text} Stats below are incomplete
      {pending > 0 ? ` (${pending.toLocaleString()} pending).` : "."}
    </div>
  );
}

export function completenessItems(records: SlimRecord[]): CompletenessItem[] {
  const total = records.length;
  const make = (key: string, label: string, known: number): CompletenessItem => ({
    key,
    label,
    known,
    total,
    rate: total ? known / total : null,
  });
  return [
    make("degree", "Degree", records.filter((r) => r.degree !== null).length),
    make("field", "Field", records.filter((r) => r.field !== null).length),
    make("profession", "Profession", records.filter((r) => r.profession !== null && r.profession !== undefined).length),
    make("law_firm", "Law firm", records.filter((r) => r.law_firm !== null).length),
    make("citations", "Citations", records.filter((r) => r.citations[1]).length),
    make("publications", "Publications", records.filter((r) => r.publications[1]).length),
    make("patents", "Patents", records.filter((r) => r.patents?.[1]).length),
    make("processing_days", "Processing days", records.filter((r) => r.processing_days[1]).length),
    make("premium", "Premium processing", records.filter((r) => r.premium_processing !== null).length),
    make("rfe", "RFE", records.filter((r) => r.was_rfed !== null).length),
  ];
}

export function CompletenessStrip({ records }: { records: SlimRecord[] }) {
  return (
    <section className="completeness" aria-label="Data completeness">
      <div className="completeness-head">
        <h3>Data completeness</h3>
        <span className="muted">current view</span>
      </div>
      <div className="completeness-grid">
        {completenessItems(records).map((item) => (
          <div className="completeness-item" key={item.key}>
            <span>{item.label}</span>
            <strong>{pct(item.rate)}</strong>
            <small>{item.known.toLocaleString()} / {item.total.toLocaleString()}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
