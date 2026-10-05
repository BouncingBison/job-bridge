"""Identity and hashing, schema v9 section 8.

Two jobs here:

1. Build stable IDs from normalized inputs, recording which input produced them.
2. Recognize when two different URLs point at the same requisition. The contract
   hashes the canonical URL, so a posting reached once through job-boards.greenhouse.io
   and once through boards-api.greenhouse.io would otherwise arrive as two records.
   `requisition_key` collapses those to one key per (ATS, board, job id).

Open item: the contract says "hash(...)" without fixing byte layout. IDs produced here
are sha256 over the normalized fields joined by "|". Until that layout is confirmed
against the other side of the bridge, treat recomputed IDs as this tool's own and do
not use them to overwrite existing IDs.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that track a click rather than identify a requisition.
_TRACKING = re.compile(r"^(utm_.*|gh_src|source|src|ref|referrer|lever-source.*|lever-origin|trk|fbclid|gclid)$", re.I)


def normalize(text: str | None) -> str:
    """Unicode NFC, collapsed whitespace, lowercase."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def canonical_url(url: str | None) -> str | None:
    """Lowercase scheme and host, drop fragments and tracking parameters, keep
    requisition-defining parameters such as gh_jid, drop a trailing slash."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _TRACKING.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(sorted(query)), ""))


def _sha(*fields: str) -> str:
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def job_id(employer: str, initial_title: str, employer_url: str | None, detected_date: str) -> tuple[str, str]:
    """Return (id, id_basis)."""
    url = canonical_url(employer_url)
    if url:
        return _sha(normalize(employer), normalize(initial_title), url), "url"
    return _sha(normalize(employer), normalize(initial_title), detected_date), "title_date"


def application_id(employer: str, title_exact: str, requisition_url: str | None, applied_date: str) -> tuple[str, str]:
    url = canonical_url(requisition_url)
    if url:
        return "app_" + _sha(normalize(employer), url, applied_date), "url"
    return "app_" + _sha(normalize(employer), normalize(title_exact), applied_date), "title_date"


def signal_id(organization: str, kind: str, source_url: str | None) -> str:
    return "signal_" + _sha(normalize(organization), normalize(kind), canonical_url(source_url) or "")


_ID_RE = re.compile(r"^(app_|signal_)?[0-9a-f]{64}$")


def well_formed_id(value: object, record_type: str | None = None) -> bool:
    if not isinstance(value, str) or not _ID_RE.match(value):
        return False
    if record_type == "application":
        return value.startswith("app_")
    if record_type == "signal":
        return value.startswith("signal_")
    if record_type == "job":
        return not value.startswith(("app_", "signal_"))
    return True


# Requisition keys across ATS URL shapes.
_PATTERNS = [
    # Greenhouse: boards.greenhouse.io/<board>/jobs/<id>, job-boards.greenhouse.io/<board>/jobs/<id>,
    # boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>
    ("greenhouse", re.compile(r"greenhouse\.io/(?:v1/boards/)?(?P<board>[\w-]+)/jobs/(?P<job>\d+)", re.I)),
    # Lever: jobs.lever.co/<board>/<uuid>, api.lever.co/v0/postings/<board>/<uuid>
    ("lever", re.compile(r"lever\.co/(?:v0/postings/)?(?P<board>[\w.-]+)/(?P<job>[0-9a-f-]{36})", re.I)),
    # Ashby: jobs.ashbyhq.com/<board>/<uuid>
    ("ashby", re.compile(r"ashbyhq\.com/(?:posting-api/job-board/)?(?P<board>[\w.-]+)/(?P<job>[0-9a-f-]{36})", re.I)),
]


def requisition_key(url: str | None) -> str | None:
    """'greenhouse:acme:1234567' for any Greenhouse URL shape of that posting.
    A gh_jid parameter on a company careers page also resolves, with board unknown.
    Returns None for URLs this module cannot map, which is not evidence of anything."""
    if not url:
        return None
    for ats, pattern in _PATTERNS:
        m = pattern.search(url)
        if m:
            return f"{ats}:{m.group('board').lower()}:{m.group('job').lower()}"
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if m:
        return f"greenhouse:?:{m.group(1)}"
    return None
