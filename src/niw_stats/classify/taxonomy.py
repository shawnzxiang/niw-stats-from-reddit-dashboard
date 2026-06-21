"""Deterministic, code-versioned normalisation of free-text fields.

Kept in Python (not left to the model) so the taxonomy is stable and testable.
"""

from __future__ import annotations

import re

# Ordered: first bucket whose keyword appears wins.
_FIELD_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("CS/AI", ("machine learning", "deep learning", "artificial intelligence", " ai ", "ai/", "nlp",
               "computer vision", "ml ", "data science", "llm", "reinforcement learning")),
    ("Software/Systems", ("software", "distributed systems", "databases", "compiler", "cybersecurity",
                          "security", "networking", "cloud", "devops")),
    ("EE/Hardware", ("electrical engineering", "semiconductor", "vlsi", "circuits", "embedded",
                     "signal processing", "photonics", "hardware")),
    ("Biology", ("biology", "genomics", "genetics", "neuroscience", "microbiology", "ecology",
                 "molecular biology", "bioinformatics")),
    ("Biomedical/Medicine", ("medicine", "clinical", "medical", "biomedical", "pharma", "oncology",
                             "immunology", "public health", "epidemiology", "nursing")),
    ("Chemistry", ("chemistry", "chemical engineering", "catalysis", "electrochemistry")),
    ("Materials", ("materials science", "materials", "nanomaterials", "polymer", "metallurgy")),
    ("Physics", ("physics", "astrophysics", "quantum", "optics", "particle")),
    ("Math/Stats", ("mathematics", "statistics", "applied math", "probability", "operations research")),
    ("Economics/Finance", ("economics", "finance", "econometrics", "accounting", "actuarial")),
    ("Civil/Mechanical", ("civil engineering", "mechanical engineering", "structural", "robotics",
                          "aerospace", "manufacturing", "thermodynamics")),
    ("Environmental/Energy", ("environmental", "energy", "renewable", "climate", "sustainability",
                              "petroleum", "geology")),
    ("Social Sciences", ("psychology", "sociology", "political science", "education", "linguistics")),
]

_FIRM_DIY = (" diy ", "self petition", "self petitioned", "self filed", "self file",
             "pro se", "no lawyer", "no attorney", "without a lawyer", "without an attorney")
_FIRM_CHEN = ("wegreen", "we greened", " chen ", "chen immigration", "chen associates",
              "north america immigration", "greenedway", "greened way")
_FIRM_ELLIS_PORTER = (" ep ", "ellis porter", "ellisporter")
_FIRM_RAJU = ("raju",)
_FIRM_COLOMBO = ("colombo", "columbo", "colombu", " c and h ")
_FIRM_SEDAGHAT = ("sedaghat",)
_FIRM_DUNN = ("dunn", "arkell")
_FIRM_PEAK = ("peak immigration",)
_FIRM_UNKNOWN = {
    "other", "unknown", "not mentioned", "not specified", "none", "n a", "na", "null",
}


def _firm_text(raw: str) -> str:
    text = raw.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    collapsed = re.sub(r"\s+", " ", text).strip()
    return f" {collapsed} "


# Generic legal-entity suffixes stripped from un-bucketed firm names so near-duplicates
# (e.g. "Ashoori" vs "Ashoori Law Firm") collapse to one canonical label.
_FIRM_SUFFIXES = (
    "law firm", "law group", "law offices", "law office", "attorneys at law", "attorneys",
    "attorney", "and associates", "associates", "immigration law", "immigration", "legal",
    "pllc", "llp", "llc", "p c", "pc", "law",
)


def _canonical_firm(raw_clean: str) -> str:
    low = re.sub(r"[.,]", "", raw_clean.lower()).strip()
    stripped = False
    changed = True
    while changed:
        changed = False
        for suffix in _FIRM_SUFFIXES:
            if low.endswith(" " + suffix):
                low = low[: -len(suffix)].strip()
                stripped = True
                changed = True
                break
    if not stripped or not low:
        return raw_clean  # nothing generic to strip — preserve original (incl. acronyms)
    return " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in low.split())


def normalize_field(raw: str | None) -> str | None:
    if not raw:
        return None
    text = f" {raw.lower()} "
    for bucket, keywords in _FIELD_MAP:
        if any(kw in text for kw in keywords):
            return bucket
    return "Other"


def normalize_law_firm(raw: str | None) -> str | None:
    if not raw:
        return None
    raw_clean = re.sub(r"\s+", " ", raw.strip())
    text = _firm_text(raw)
    if text.strip() in _FIRM_UNKNOWN:
        return None
    if any(kw in text for kw in _FIRM_DIY):
        return "DIY/Self-petition"
    if any(kw in text for kw in _FIRM_CHEN):
        return "Chen/WeGreened"
    if any(kw in text for kw in _FIRM_ELLIS_PORTER):
        return "Ellis Porter"
    if any(kw in text for kw in _FIRM_RAJU):
        return "Raju Law"
    if any(kw in text for kw in _FIRM_COLOMBO):
        return "Colombo & Hurd"
    if any(kw in text for kw in _FIRM_SEDAGHAT):
        return "Sedaghat Law"
    if any(kw in text for kw in _FIRM_DUNN):
        return "Dunn Law"
    if any(kw in text for kw in _FIRM_PEAK):
        return "Peak Immigration"
    return _canonical_firm(raw_clean) if raw_clean else None


# Ordered: first bucket whose keyword appears wins. Specific roles BEFORE generic ones
# (e.g. "software engineer" before bare "engineer"; "data scientist" before "scientist").
_PROFESSION_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("PhD Student", ("phd student", "ph d student", "phd candidate", "ph d candidate",
                     "doctoral student", "doctoral candidate", "phd researcher", "phd in",
                     "grad student", "graduate student")),
    ("Professor/Faculty", ("professor", "faculty", "lecturer", "tenure", " tt ", "instructor")),
    ("Data Scientist/Engineer", ("data scientist", "data analyst", "data engineer", "ml engineer",
                                 "machine learning engineer", "ai engineer", "applied scientist",
                                 "business intelligence", "data science", "statistician",
                                 "biostatistician", "quantitative")),
    # Non-software "<x> developer" roles (industrial/infrastructure) must be caught BEFORE the
    # Software Engineer "developer" catch-all below, else e.g. "Project Developer at a water
    # treatment company" wrongly lands in Software Engineer.
    ("Engineer (other)", ("project developer", "infrastructure developer", "process developer",
                          "energy developer", "renewable developer", "solar developer",
                          "hardware developer")),
    # Any "software" mention => Software Engineer (catches "software/system engineer",
    # "software professional", etc.). PhD/Professor/Data-Scientist are matched above, so
    # "PhD in software" or an explicit "AI engineer" still wins its own category.
    ("Software Engineer", ("software", " swe ", " sde ", "cybersecurity", "security engineer",
                           "hpc engineer", "devops", "solutions architect", "solution architect",
                           "cloud engineer", "backend", "frontend", "full stack", "fullstack",
                           "qa tester", "programmer", "developer")),
    ("Postdoc/Researcher", ("postdoc", "post doc", "postdoctoral", "post doctoral", "research fellow",
                            "research associate", "research scientist", "researcher", "scientist",
                            "research staff", " r d ")),
    ("Physician/Clinician", ("physician", "doctor of", "veterinary", "therapist", "nurse", "clinician",
                             "surgeon", "medical doctor", "dentist", "pharmacist", "physical therapy",
                             " cra ", "resident")),
    ("Engineer (other)", ("engineer", "engineering", "architect")),
    ("Entrepreneur/Founder", ("entrepreneur", "founder", "business owner", "startup", " ceo ", " cto ")),
    ("Finance/Business", ("finance", "banking", " bank ", "investment", "trading", "supply chain",
                          "consultant", "business analyst", "program manager", "product manager",
                          "executive", "strategist", "operations", "accountant", "economist",
                          "analyst", "manager")),
    ("Student (other)", ("student", "master", " msc ", "undergrad")),
]


def normalize_profession(raw: str | None) -> str | None:
    if not raw:
        return None
    text = " " + re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip() + " "
    if text.strip() in _FIRM_UNKNOWN:
        return None
    for bucket, keywords in _PROFESSION_MAP:
        if any(kw in text for kw in keywords):
            return bucket
    return "Other"
