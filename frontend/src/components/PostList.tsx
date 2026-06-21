import { Fragment, useEffect, useState } from "react";

import type { KnownPair, SlimRecord } from "../types";

const PAGE_SIZE = 25;
const COLUMN_COUNT = 13;
// Column widths as % of the table so table-layout:fixed makes it fit any screen; text wraps.
// Order: Date, Outcome, Degree, Field, Profession, Law firm, Cit., Pubs, Pat., Days, PP, RFE, Post.
const COL_WIDTHS = ["8%", "7%", "7%", "9%", "10%", "10%", "5%", "5%", "5%", "5%", "6%", "5%", "18%"];

function fmtDate(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(0, 10);
}
function num(pair: KnownPair | undefined): string {
  if (!pair) return "—";
  const [v, known] = pair;
  return known && v !== null ? String(v) : "—";
}
function premium(v: boolean | null): string {
  return v === null ? "—" : v ? "Premium" : "Regular";
}
function rfe(v: boolean | null): string {
  return v === null ? "—" : v ? "RFE" : "No RFE";
}
function fmtDateTime(epoch?: number | null): string {
  return epoch ? new Date(epoch * 1000).toISOString().replace("T", " ").slice(0, 16) : "—";
}
function version(r: SlimRecord): string {
  return r.prompt_version && r.schema_version ? `${r.prompt_version}/${r.schema_version}` : "—";
}
function sourceText(record: SlimRecord): string {
  const parts = [
    `TITLE: ${record.title ?? ""}`,
    record.flair ? `FLAIR: ${record.flair}` : null,
    "",
    record.selftext?.trim() || "[body unavailable]",
  ];
  if (record.op_comments?.trim()) {
    parts.push("", "OP COMMENTS:", record.op_comments.trim());
  }
  return parts.filter((p): p is string => p !== null).join("\n");
}

function MetadataGrid({ record }: { record: SlimRecord }) {
  const rows: [string, string][] = [
    ["Version", version(record)],
    ["Run", record.run ?? "—"],
    ["Classified", fmtDateTime(record.classified_at)],
    ["Outcome", record.outcome ?? "—"],
    ["Degree", record.degree ?? "—"],
    ["Field", record.field ?? "—"],
    ["Profession", record.profession ?? "—"],
    ["Profession (raw)", record.profession_raw ?? "—"],
    ["Law firm", record.law_firm ?? "—"],
    ["Citations", num(record.citations)],
    ["Publications", num(record.publications)],
    ["Patents", num(record.patents)],
    ["Years exp.", num(record.years_experience)],
    ["Processing days", num(record.processing_days)],
    ["Premium", premium(record.premium_processing)],
    ["RFE", rfe(record.was_rfed)],
    ["RFE date", record.rfe_date ?? "—"],
    ["RFE response", record.rfe_response_date ?? "—"],
  ];
  return (
    <dl className="audit-meta-grid">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function AuditPane({ record }: { record: SlimRecord }) {
  return (
    <div className="audit-pane">
      <div className="audit-col">
        <div className="audit-head">
          <h4>Extracted metadata</h4>
          <span className={`badge ${record.outcome ?? "none"}`}>{record.outcome ?? "—"}</span>
        </div>
        <MetadataGrid record={record} />
      </div>
      <div className="audit-col source">
        <div className="audit-head">
          <h4>Post text</h4>
          {record.permalink && (
            <a href={`https://www.reddit.com${record.permalink}`} target="_blank" rel="noreferrer">
              Open Reddit
            </a>
          )}
        </div>
        <pre>{sourceText(record)}</pre>
      </div>
    </div>
  );
}

export function PostList({ records }: { records: SlimRecord[] }) {
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Reset to the first page whenever the filtered set changes.
  useEffect(() => {
    setPage(0);
    setSelectedId(null);
  }, [records]);

  const sorted = [...records].sort((a, b) => b.created_utc - a.created_utc);
  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const start = safePage * PAGE_SIZE;
  const slice = sorted.slice(start, start + PAGE_SIZE);

  useEffect(() => {
    setSelectedId(null);
  }, [safePage]);

  return (
    <section className="postlist">
      <div className="postlist-head">
        <h3>Matching posts</h3>
        <span className="muted">
          {total.toLocaleString()} post{total !== 1 ? "s" : ""}
          {total > 0 ? ` · showing ${start + 1}–${Math.min(start + PAGE_SIZE, total)}` : ""}
        </span>
      </div>

      {total === 0 ? (
        <div className="center">No posts match the current filters.</div>
      ) : (
        <>
          <div className="ptable-wrap">
            <table className="ptable">
              <colgroup>
                {COL_WIDTHS.map((w, i) => (
                  <col key={i} style={{ width: w }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  <th className="date">Date</th>
                  <th>Outcome</th>
                  <th>Degree</th>
                  <th>Field</th>
                  <th>Profession</th>
                  <th>Law firm</th>
                  <th className="num">Cit.</th>
                  <th className="num">Pubs</th>
                  <th className="num">Pat.</th>
                  <th className="num">Days</th>
                  <th title="Premium processing">PP</th>
                  <th>RFE</th>
                  <th>Post</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((r, i) => {
                  const rowKey = r.id ?? `${start + i}`;
                  const isSelected = selectedId === rowKey;
                  return (
                    <Fragment key={rowKey}>
                      <tr
                        className={isSelected ? "selected" : ""}
                        onClick={() => setSelectedId(rowKey)}
                      >
                        <td className="date">{fmtDate(r.created_utc)}</td>
                        <td>
                          <span className={`badge ${r.outcome ?? "none"}`}>{r.outcome ?? "—"}</span>
                        </td>
                        <td>{r.degree ?? "—"}</td>
                        <td>{r.field ?? "—"}</td>
                        <td className="prof" title={r.profession ?? undefined}>{r.profession ?? "—"}</td>
                        <td className="firm" title={r.law_firm ?? undefined}>{r.law_firm ?? "—"}</td>
                        <td className="num">{num(r.citations)}</td>
                        <td className="num">{num(r.publications)}</td>
                        <td className="num">{num(r.patents)}</td>
                        <td className="num">{num(r.processing_days)}</td>
                        <td>{premium(r.premium_processing)}</td>
                        <td>{rfe(r.was_rfed)}</td>
                        <td className="title">
                          <button type="button" className="link-button" onClick={() => setSelectedId(rowKey)}>
                            {r.title ?? "(view post)"}
                          </button>
                          {r.refiled && r.refiled_url && (
                            <a
                              href={`https://www.reddit.com${r.refiled_url}`}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              title="This author was later approved after re-filing"
                              style={{ marginLeft: 8, fontSize: 11, background: "#E1F5EE", color: "#085041", borderRadius: 6, padding: "1px 7px", textDecoration: "none", whiteSpace: "nowrap" }}
                            >
                              ↩ re-filed → approved ↗
                            </a>
                          )}
                          {r.refile_approval && (
                            <span style={{ marginLeft: 8, fontSize: 11, background: "#E1F5EE", color: "#085041", borderRadius: 6, padding: "1px 7px", whiteSpace: "nowrap" }}>
                              ↩ approval after re-file
                            </span>
                          )}
                        </td>
                      </tr>
                      {isSelected && (
                        <tr className="audit-row">
                          <td colSpan={COLUMN_COUNT}>
                            <AuditPane record={r} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {pages > 1 && (
        <div className="pager">
          <button disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
            ‹ Prev
          </button>
          <span className="muted">Page {safePage + 1} / {pages}</span>
          <button disabled={safePage >= pages - 1} onClick={() => setPage(safePage + 1)}>
            Next ›
          </button>
        </div>
      )}
    </section>
  );
}
