"""Read a posting from the employer's own ATS.

The one rule this module exists to enforce: a failed, blocked or partial fetch is
UNKNOWN, never CLOSED. Two wrong kills came from treating a failed fetch as closure,
and a live posting was once missing from its own board listing while its job endpoint
still served it. So:

- status "open" only when the job endpoint itself returns the posting.
- status "closed" only on positive closure evidence (an explicit expiry or
  no-longer-available notice in the employer's own page text).
- everything else, including 404s and absence from a board list, is "unknown" with
  the reason recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests

from .ids import requisition_key

TIMEOUT = 20
UA = {"User-Agent": "job-bridge/0.1 (+personal job search tooling)"}
CLOSURE_TEXT = re.compile(r"(this job has expired|no longer (available|accepting)|position (has been )?filled|job is closed)", re.I)


@dataclass
class Posting:
    status: str                      # open | closed | unknown
    reason: str
    key: str | None = None
    title: str | None = None
    location: str | None = None
    first_published: str | None = None
    updated_at: str | None = None
    url: str | None = None
    pay_text: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


def _get(url: str) -> requests.Response | None:
    try:
        return requests.get(url, headers=UA, timeout=TIMEOUT)
    except requests.RequestException:
        return None


def _pay(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"(?:USD|\$)\s?[\d,.]+\s?[kK]?\s?(?:-|to|–)\s?(?:USD|\$)?\s?[\d,.]+\s?[kK]?(?:\s?(?:per hour|/hr|hourly))?", text)
    return m.group(0) if m else None


def fetch(url: str) -> Posting:
    key = requisition_key(url)
    if not key:
        return Posting("unknown", "URL is not a recognized Greenhouse, Lever or Ashby posting", key=None, url=url)
    ats, board, job = key.split(":")
    if ats == "greenhouse":
        return _greenhouse(board, job, key, url)
    if ats == "lever":
        return _lever(board, job, key, url)
    return _ashby(board, job, key, url)


def _greenhouse(board: str, job: str, key: str, url: str) -> Posting:
    if board == "?":
        return Posting("unknown", "gh_jid found but board token unknown; resolve the board before checking", key=key, url=url)
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?pay_transparency=true")
    if r is None:
        return Posting("unknown", "fetch failed (network)", key=key, url=url)
    if r.status_code == 404:
        return Posting("unknown", "404 from job endpoint; confirm the board token is right before treating as closed", key=key, url=url)
    if r.status_code != 200:
        return Posting("unknown", f"HTTP {r.status_code}", key=key, url=url)
    d = r.json()
    pay = None
    ranges = d.get("pay_input_ranges") or []
    if ranges:
        p = ranges[0]
        pay = f"{p.get('currency_type', '')} {int(p.get('min_cents', 0)) // 100:,}-{int(p.get('max_cents', 0)) // 100:,}".strip()
    return Posting("open", "job endpoint served the posting", key=key, title=d.get("title"),
                   location=(d.get("location") or {}).get("name"), first_published=d.get("first_published"),
                   updated_at=d.get("updated_at"), url=d.get("absolute_url") or url,
                   pay_text=pay or _pay(d.get("content")), raw=d)


def _lever(board: str, job: str, key: str, url: str) -> Posting:
    r = _get(f"https://api.lever.co/v0/postings/{board}/{job}")
    if r is None:
        return Posting("unknown", "fetch failed (network)", key=key, url=url)
    if r.status_code != 200:
        return Posting("unknown", f"HTTP {r.status_code} from Lever postings API", key=key, url=url)
    d = r.json()
    sal = d.get("salaryRange") or {}
    pay = f"{sal.get('currency', '')} {sal.get('min', '')}-{sal.get('max', '')}".strip() if sal else _pay(d.get("descriptionPlain"))
    created = d.get("createdAt")
    if isinstance(created, (int, float)):
        from datetime import datetime, timezone
        created = datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
    return Posting("open", "postings API served the posting", key=key, title=d.get("text"),
                   location=(d.get("categories") or {}).get("location"), first_published=created,
                   url=d.get("hostedUrl") or url, pay_text=pay, raw=d)


def _ashby(board: str, job: str, key: str, url: str) -> Posting:
    r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
    if r is None:
        return Posting("unknown", "fetch failed (network)", key=key, url=url)
    if r.status_code != 200:
        return Posting("unknown", f"HTTP {r.status_code} from Ashby posting API", key=key, url=url)
    for d in r.json().get("jobs", []):
        if str(d.get("id", "")).lower() == job:
            comp = (d.get("compensation") or {}).get("compensationTierSummary")
            return Posting("open", "board API lists the posting", key=key, title=d.get("title"),
                           location=d.get("location"), first_published=d.get("publishedAt"),
                           updated_at=d.get("updatedAt"), url=d.get("jobUrl") or url, pay_text=comp, raw=d)
    return Posting("unknown", "absent from the board listing; absence is not closure evidence", key=key, url=url)


def closure_evidence(page_text: str) -> bool:
    """True only when the employer's own page states the posting is closed."""
    return bool(CLOSURE_TEXT.search(page_text or ""))
