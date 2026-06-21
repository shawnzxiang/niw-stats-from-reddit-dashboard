"""One-off privacy audit of the PUBLISHED snapshot before going public.

Scans the free-text fields (title, selftext, op_comments) + metadata of every record in
frontend/public/snapshot.json for things you probably shouldn't republish:
  - hard identifiers: email, phone, SSN, USCIS receipt #, A-number
  - de-anonymizing links: LinkedIn / Google Scholar / ORCID / ResearchGate / personal academic profiles
  - withdrawn content: posts the OP later deleted/removed
  - the usernames themselves (the known "keep links" tradeoff — quantified here)

Prints counts + a few examples (with permalinks) so you can eyeball and decide.
"""
from __future__ import annotations
import json, re, sys
from collections import Counter
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("-")]
ASSERT_CLEAN = "--assert-clean" in sys.argv  # exit non-zero if the snapshot still carries PII
snap_path = Path(args[0] if args else "frontend/public/snapshot.json")
data = json.loads(snap_path.read_text())
records = data["records"]

def text_of(r: dict) -> str:
    parts = [str(r.get("title") or ""), str(r.get("selftext") or "")]
    oc = r.get("op_comments")
    if oc:
        parts.append(oc if isinstance(oc, str) else json.dumps(oc))
    return "\n".join(parts)

DETECTORS = {
    "email":          re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone":          re.compile(r"(?<!\d)(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?!\d)"),
    "ssn":            re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "uscis_receipt":  re.compile(r"\b(?:EAC|WAC|SRC|LIN|IOE|MSC|YSC|NBC)\s?\d{10}\b", re.I),
    "a_number":       re.compile(r"\bA[-#\s]?\d{8,9}\b"),
    "linkedin":       re.compile(r"linkedin\.com/(?:in|pub)/[\w-]+", re.I),
    "google_scholar": re.compile(r"scholar\.google\.[a-z.]+/citations\?\S+", re.I),
    "orcid":          re.compile(r"orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dxX]", re.I),
    "researchgate":   re.compile(r"researchgate\.net/profile/[\w-]+", re.I),
    "github_profile": re.compile(r"github\.com/[\w-]+(?:/[\w.-]+)?", re.I),
    "other_profile":  re.compile(r"\b(?:twitter\.com|x\.com|facebook\.com|instagram\.com)/[\w.]+", re.I),
}
# light redaction so the audit log itself doesn't echo raw secrets
REDACT = {"email", "phone", "ssn", "a_number"}
def show(kind: str, m: str) -> str:
    if kind in REDACT and len(m) > 4:
        return m[:2] + "…" + m[-2:]
    return m

hits: dict[str, list] = {k: [] for k in DETECTORS}
for r in records:
    t = text_of(r)
    for kind, rx in DETECTORS.items():
        for m in rx.findall(t):
            s = m if isinstance(m, str) else m[0]
            hits[kind].append((r.get("id"), r.get("permalink"), s))

# withdrawn / empty content
deleted_author = [r for r in records if str(r.get("author")).lower() in ("[deleted]", "none", "")]
removed_body  = [r for r in records if str(r.get("selftext")).strip().lower() in ("[deleted]", "[removed]")]
authors = Counter(r.get("author") for r in records if r.get("author"))

print(f"\n=== snapshot: {snap_path}  ({len(records)} records) ===\n")
print(f"distinct usernames published : {len([a for a in authors if a and str(a).lower() not in ('[deleted]','none')])}")
print(f"posts w/ deleted/none author : {len(deleted_author)}")
print(f"posts w/ [deleted]/[removed] body : {len(removed_body)}")

print("\n--- HARD IDENTIFIERS (review every one) ---")
for kind in ("email","phone","ssn","uscis_receipt","a_number"):
    h = hits[kind]
    print(f"  {kind:14s}: {len(h)}")
    for pid, link, m in h[:6]:
        print(f"      {show(kind,m)!r:28s}  {pid}  https://reddit.com{link}")

print("\n--- DE-ANONYMIZING LINKS (tie a username to a real identity) ---")
for kind in ("linkedin","google_scholar","orcid","researchgate","github_profile","other_profile"):
    h = hits[kind]
    if not h:
        print(f"  {kind:14s}: 0")
        continue
    print(f"  {kind:14s}: {len(h)}")
    for pid, link, m in h[:6]:
        print(f"      {m!r:48s}  {pid}  https://reddit.com{link}")

# top recurring authors (someone posting a lot = more re-identifiable footprint)
print("\n--- most-frequent usernames in the dataset ---")
for a, n in authors.most_common(8):
    if a and str(a).lower() not in ("[deleted]","none"):
        print(f"  {n:3d}  u/{a}")

# --- deploy gate ------------------------------------------------------------
if ASSERT_CLEAN:
    forbidden_keys = sorted({k for r in records for k in ("author", "selftext", "op_comments") if k in r})
    hard = [(k, hits[k]) for k in ("email", "phone", "ssn", "uscis_receipt", "a_number") if hits[k]]
    problems = []
    if forbidden_keys:
        problems.append(f"records still contain PII keys: {forbidden_keys}")
    if hard:
        problems.append("hard identifiers present: " + ", ".join(f"{k}×{len(v)}" for k, v in hard))
    if problems:
        print("\n❌ ASSERT-CLEAN FAILED — refusing to publish:")
        for p in problems:
            print(f"   - {p}")
        sys.exit(1)
    print("\n✅ ASSERT-CLEAN PASSED — no PII keys or hard identifiers; safe to publish.")
