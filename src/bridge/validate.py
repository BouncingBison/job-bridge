"""Validation for the Bridge Data Contract, schema v9.

Three layers, in the order the contract states them (section 10, Mechanics):

1. Per-line structure: JSON parses, schema_version is current, required fields exist,
   every enum value sits inside its closed list, the id is well formed.
2. The legality matrix: a job or verdict row is valid only if it matches one of the
   eight rows. Anything else is invalid by construction, not by enumeration.
3. Cross-record integrity: reciprocal links, the post-application flag, URL and ID
   agreement, door evidence, and two checks this tool adds because the contract's
   failure history calls for them: conflicting verdicts for one id across run files,
   and one requisition carried under two ids.

Nothing is silently dropped. Every problem becomes a Finding, and records written under
an earlier schema version are reported as `legacy`, never rejected (section 2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from . import enums as E
from .ids import requisition_key, well_formed_id

ERROR, WARNING, LEGACY = "error", "warning", "legacy"


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""
    line: int = 0
    record_id: str = ""

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.file else "-"
        rid = f" [{self.record_id[:12]}]" if self.record_id else ""
        return f"{self.severity.upper():7} {self.rule:22} {where}{rid}  {self.message}"


@dataclass
class Record:
    data: dict
    file: str
    line: int

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))

    @property
    def type(self) -> str:
        return str(self.data.get("record_type", ""))


@dataclass
class Config:
    """Inputs the contract recomputes rather than trusts. years_as_of comes from the
    candidate profile; without it the hold-release-date check is skipped and says so."""
    years_as_of: date | None = None
    warn_unknown_fields: bool = True


# ---------------------------------------------------------------- field tables

COMMON = ["schema_version", "id", "record_type", "detected_date", "source"]
COMMON_NULLABLE = ["source_url"]

REQUIRED = {
    "job": ["event", "employer", "title", "location", "url_source", "id_basis", "verdict", "queue_shape"],
    "verdict": ["verdict", "decision_date", "queue_shape"],
    "application": [
        "employer", "title_exact", "location", "url_source", "applied_date", "resume_variant",
        "rate_or_salary_asked", "source_of_discovery", "job_id", "id_basis",
        "confirmation_received", "status",
    ],
    "signal": [
        "event", "kind", "move_type", "organization", "headline", "facts", "hypothesis",
        "hypothesis_status", "vacancy_confirmed", "first_observed", "disconfirming_condition",
    ],
    "source": [
        "source_kind", "label", "last_checked", "check_interval_days",
        "change_intervals", "posting_count_last",
    ],
}
REQUIRED_NULLABLE = {
    "job": ["employer_url"],
    "application": ["requisition_url"],
    "source": ["last_changed"],
}

ENUM_FIELDS = {
    "record_type": E.RECORD_TYPE, "event": E.EVENT, "verdict": E.VERDICT,
    "cause_primary": E.CAUSE, "override_basis": E.OVERRIDE_BASIS, "hold_basis": E.HOLD_BASIS,
    "hold_release_type": E.HOLD_RELEASE_TYPE, "url_source": E.URL_SOURCE, "id_basis": E.ID_BASIS,
    "source_of_discovery": E.SOURCE_OF_DISCOVERY, "kind": E.SIGNAL_KIND, "move_type": E.MOVE_TYPE,
    "hypothesis_status": E.HYPOTHESIS_STATUS, "queue_shape": E.QUEUE_SHAPE,
    "source_kind": E.SOURCE_KIND, "verdict_before": E.VERDICT, "verdict_after": E.VERDICT,
}
ENUM_LIST_FIELDS = {"causes_all": E.CAUSE, "queue_signals": E.QUEUE_SIGNALS}

HOLD_FIELDS = ["hold_basis", "hold_set_date", "hold_release_type", "hold_release_date", "hold_release_event"]
YEARS_FIELDS = ["years_required", "years_held", "short_by"]
CHANGE_ONLY = ["verdict_before", "verdict_after", "gate_moved"]

# Optional fields the contract names. Anything outside these plus the required lists is
# reported as a warning, because a field the contract does not define is a field no
# validator on the other side will read.
KNOWN_OPTIONAL = {
    "job": {"causes_all", "cause_detail", "cause_primary", "override_applied", "override_basis",
            "queue_signals", "application_id", "change_note", "edit_count", "changed_post_application",
            "salary", "posted_date", "description", "surfaced_because", "prefilters", "url_history",
            *HOLD_FIELDS, *YEARS_FIELDS, *CHANGE_ONLY},
    "verdict": {"cause_primary", "causes_all", "cause_detail", "gate", "note", "queue_signals",
                "override_applied", "override_basis", *HOLD_FIELDS, *YEARS_FIELDS},
    "application": set(),
    "signal": {"hire_observed", "lag_days", "named_people"},
    "source": {"override_until", "override_reason"},
}


# ---------------------------------------------------------------- loading

def load(paths: Iterable[str | Path]) -> tuple[list[Record], list[Finding]]:
    records, findings = [], []
    for p in paths:
        p = Path(p)
        for n, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                findings.append(Finding(ERROR, "json", f"line does not parse: {exc.msg}", p.name, n))
                continue
            if not isinstance(obj, dict):
                findings.append(Finding(ERROR, "json", "line is not a JSON object", p.name, n))
                continue
            records.append(Record(obj, p.name, n))
    return records, findings


# ---------------------------------------------------------------- per-record

def _present(d: dict, k: str) -> bool:
    return k in d and d[k] is not None


def check_structure(rec: Record, cfg: Config) -> list[Finding]:
    d, out = rec.data, []

    def f(sev, rule, msg):
        out.append(Finding(sev, rule, msg, rec.file, rec.line, rec.id))

    version = d.get("schema_version", 2)  # section 2: absent is read as 2
    if version != E.SCHEMA_VERSION:
        f(LEGACY if isinstance(version, int) and version < E.SCHEMA_VERSION else ERROR,
          "schema_version", f"schema_version {version}, current is {E.SCHEMA_VERSION}")

    rtype = d.get("record_type")
    if rtype not in E.RECORD_TYPE:
        f(ERROR, "record_type", f"record_type {rtype!r} is not in the closed list")
        return out

    for k in COMMON + REQUIRED.get(rtype, []):
        if k not in d or d[k] in (None, ""):
            f(ERROR, "required", f"missing required field {k}")
    for k in COMMON_NULLABLE + REQUIRED_NULLABLE.get(rtype, []):
        if k not in d:
            f(ERROR, "required", f"missing required nullable field {k} (null is legal, absence is not)")

    if not well_formed_id(d.get("id"), rtype):
        f(ERROR, "id", f"id {d.get('id')!r} is not well formed for a {rtype} record")

    for k, allowed in ENUM_FIELDS.items():
        if _present(d, k) and d[k] not in allowed:
            f(ERROR, "enum", f"{k}={d[k]!r} is outside its closed list")
    for k, allowed in ENUM_LIST_FIELDS.items():
        if _present(d, k):
            if not isinstance(d[k], list):
                f(ERROR, "enum", f"{k} must be an array")
            else:
                for v in d[k]:
                    if v not in allowed:
                        f(ERROR, "enum", f"{k} contains {v!r}, outside its closed list")
    if rtype == "application" and _present(d, "status") and d["status"] not in E.APP_STATUS:
        f(ERROR, "enum", f"status={d['status']!r} is outside its closed list")
    if rtype == "signal" and _present(d, "vacancy_confirmed") and str(d["vacancy_confirmed"]).lower() not in E.VACANCY_CONFIRMED:
        f(ERROR, "enum", f"vacancy_confirmed={d['vacancy_confirmed']!r} is outside its closed list")

    if rtype == "signal" and not str(d.get("disconfirming_condition") or "").strip():
        f(ERROR, "signal", "disconfirming_condition is empty; a read nothing could kill is not a read")

    if rtype == "job":
        out += _check_events(rec)
    if rtype in ("job", "verdict"):
        out += check_matrix(rec, cfg)
    if rtype in ("job", "application"):
        out += _check_url_id_agreement(rec)

    if cfg.warn_unknown_fields and rtype in KNOWN_OPTIONAL:
        known = set(COMMON) | set(COMMON_NULLABLE) | set(REQUIRED.get(rtype, [])) \
            | set(REQUIRED_NULLABLE.get(rtype, [])) | KNOWN_OPTIONAL[rtype]
        extra = sorted(set(d) - known)
        if extra:
            f(WARNING, "unknown_field", "fields outside the contract: " + ", ".join(extra))
    return out


def _check_events(rec: Record) -> list[Finding]:
    d, out = rec.data, []

    def f(rule, msg):
        out.append(Finding(ERROR, rule, msg, rec.file, rec.line, rec.id))

    ev = d.get("event")
    if ev in ("changed", "modified"):
        cn = d.get("change_note")
        if not isinstance(cn, list):
            f("change_note", "change_note must be an array, one element per field moved")
        else:
            for el in cn:
                if not isinstance(el, dict) or not {"field", "before", "after"} <= set(el):
                    f("change_note", "each change_note element needs field, before and after")
        if not isinstance(d.get("edit_count"), int):
            f("change_note", "edit_count is required on changed and modified events")
    if ev == "changed":
        for k in ["verdict_before", "verdict_after", "changed_post_application"]:
            if k not in d:
                f("changed_event", f"changed event requires {k}")
        if "gate_moved" not in d:
            f("changed_event", "changed event requires gate_moved (null if none)")
    if ev == "modified":
        carried = [k for k in CHANGE_ONLY if k in d]
        if carried:
            f("modified_event", "modified never carries " + ", ".join(carried) + "; that is the definition of the split")
    if "changed_post_application" in d:
        expected = d.get("application_id") is not None
        if d["changed_post_application"] is not expected:
            f("post_application", f"changed_post_application must equal application_id != null ({expected})")
    return out


def _check_url_id_agreement(rec: Record) -> list[Finding]:
    d, out = rec.data, []
    url = d.get("employer_url") if rec.type == "job" else d.get("requisition_url")
    basis = d.get("id_basis")
    if basis == "url" and not url:
        out.append(Finding(ERROR, "url_id_agreement", "id_basis url requires a non-null canonical URL", rec.file, rec.line, rec.id))
    if basis == "title_date" and d.get("url_source") != "none":
        out.append(Finding(ERROR, "url_id_agreement", "id_basis title_date requires url_source none", rec.file, rec.line, rec.id))
    return out


# ---------------------------------------------------------------- the matrix

def check_matrix(rec: Record, cfg: Config) -> list[Finding]:
    """Section 10. Returns findings; an empty list means the row matched a matrix line."""
    d = rec.data
    v = d.get("verdict")
    cp = d.get("cause_primary")
    ca = d.get("causes_all") or []
    if not isinstance(ca, list):
        ca = []
    ca_set = set(ca)
    oa = d.get("override_applied", "ABSENT")
    ob = d.get("override_basis")
    hold_present = [k for k in HOLD_FIELDS if _present(d, k)]
    out: list[Finding] = []

    def bad(msg, rule="matrix"):
        out.append(Finding(ERROR, rule, f"{v}: {msg}", rec.file, rec.line, rec.id))

    oa_absent_or_false = oa in ("ABSENT", None, False)

    # Cross-record rules that apply to every row.
    if cp is not None and ca and cp not in ca_set:
        bad(f"cause_primary {cp} is not a member of causes_all {ca}", "cause_set")
    if ob is not None and oa is not True:
        bad("override_basis present requires override_applied true", "override_basis")
    if oa is True and not ca_set <= E.OVERRIDABLE:
        bad(f"override_applied true with non-overridable causes {sorted(ca_set - E.OVERRIDABLE)}", "overridability")
    has_years = all(k in d for k in YEARS_FIELDS)
    if ("years_gate" in ca_set) != has_years:
        bad("years fields must be present if and only if years_gate is in causes_all", "years_fields")
    if has_years:
        try:
            if int(d["years_required"]) - int(d["years_held"]) != int(d["short_by"]):
                bad("short_by does not equal years_required minus years_held", "years_fields")
        except (TypeError, ValueError):
            bad("years fields must be integers", "years_fields")
    if bool(hold_present) != (v == "HOLD"):
        bad("hold fields present if and only if verdict is HOLD", "hold_fields")
    if d.get("queue_shape") == "door" and not (set(d.get("queue_signals") or []) & E.DOOR_SIGNALS):
        bad("queue_shape door requires at least one door signal in queue_signals", "door_evidence")

    # The eight rows.
    if v == "SEND":
        if cp is not None:
            bad("cause_primary must be absent")
        if ca:
            bad("causes_all must be empty")
        if not oa_absent_or_false:
            bad("override_applied must be absent or false")
    elif v == "CHEAP_SHOT":
        if cp == "evidence_coverage":  # row 2
            if ca:
                bad("evidence_coverage row requires empty causes_all")
            if not oa_absent_or_false:
                bad("evidence_coverage row requires override_applied absent or false")
            detail = str(d.get("cause_detail") or "")
            if not any(ch.isdigit() for ch in detail):
                bad("evidence_coverage row requires cause_detail stating the count")
        elif cp in E.OVERRIDABLE:  # row 3
            if not ca_set or not ca_set <= E.OVERRIDABLE:
                bad(f"overridden row allows overridable gates only, got {ca}")
            if oa is not True:
                bad("overridden row requires override_applied true")
            if ob not in E.OVERRIDE_BASIS:
                bad("overridden row requires override_basis")
        else:
            bad(f"cause_primary {cp!r} is not legal on CHEAP_SHOT")
    elif v == "KILL":  # row 4
        if cp not in E.GATES:
            bad(f"cause_primary {cp!r} is not a gate cause; thin evidence never kills")
        if cp not in ca_set:
            bad("causes_all must contain cause_primary")
        fired_hard = ca_set & E.NON_OVERRIDABLE_GATES
        if fired_hard and cp not in E.NON_OVERRIDABLE_GATES:
            bad(f"non-overridable {sorted(fired_hard)} fired, so cause_primary must name one of them")
        if not oa_absent_or_false:
            bad("override_applied must be absent or false")
    elif v == "HOLD":
        if cp == "sequencing":  # row 5
            if ca_set != {"sequencing"}:
                bad("sequencing HOLD requires causes_all of sequencing only")
            if d.get("hold_basis") != "sequencing" or d.get("hold_release_type") != "date" or not d.get("hold_release_date"):
                bad("sequencing HOLD requires hold_basis sequencing, release type date, and a release date")
            if not oa_absent_or_false:
                bad("override_applied must be absent or false")
        elif cp == "years_gate":  # row 6
            if ca_set != {"years_gate"}:
                bad("years HOLD requires causes_all of years_gate only; a second gate makes it a KILL")
            if oa is not False:
                bad("years HOLD requires an explicit override_applied false")
            if d.get("hold_basis") != "years_distance" or d.get("hold_release_type") != "either":
                bad("years HOLD requires hold_basis years_distance and release type either")
            if not d.get("hold_release_date") or not d.get("hold_release_event"):
                bad("years HOLD requires both release fields")
            if cfg.years_as_of and d.get("hold_release_date") and has_years:
                try:
                    yrs = int(d["short_by"]) - 2
                    a = cfg.years_as_of
                    expected = a.replace(year=a.year + yrs)
                    if str(d["hold_release_date"])[:10] != expected.isoformat():
                        bad(f"hold_release_date should be {expected.isoformat()} (years_as_of plus short_by minus 2)", "hold_release_date")
                except (ValueError, TypeError):
                    bad("hold_release_date could not be recomputed", "hold_release_date")
        else:
            bad(f"cause_primary {cp!r} is not legal on HOLD")
    elif v == "READ":  # row 7
        if cp not in (None, "provenance", "evidence_coverage"):
            bad(f"cause_primary {cp!r} is not legal on READ; a fired gate resolves to KILL, CHEAP_SHOT or HOLD")
        if ca and ca_set != {"provenance"}:
            bad(f"READ allows causes_all of provenance only, or empty; got {ca}")
        if cp is None and ca:
            bad("a cause-absent READ must have empty causes_all")
        if oa != "ABSENT":
            bad("override_applied must be absent on READ")
    elif v == "WATCH":  # row 8
        if cp != "evidence_coverage":
            bad("WATCH requires cause_primary evidence_coverage")
        if ca:
            bad("WATCH requires empty causes_all")
        if oa != "ABSENT":
            bad("override_applied must be absent on WATCH")
    return out


# ---------------------------------------------------------------- cross-record

def check_cross(records: list[Record]) -> list[Finding]:
    out: list[Finding] = []
    jobs = {r.id: r for r in records if r.type == "job"}
    apps = {r.id: r for r in records if r.type == "application"}
    signals = {r.id for r in records if r.type == "signal"}

    # Reciprocal links. A link to a record type that was not loaded is a warning, not
    # an error: absence from this run's input is not absence from the bridge.
    for a in apps.values():
        jid = a.data.get("job_id")
        if jid in jobs:
            if jobs[jid].data.get("application_id") != a.id:
                out.append(Finding(ERROR, "reciprocal_link", "job record does not point back at this application", a.file, a.line, a.id))
        elif jobs:
            out.append(Finding(WARNING, "reciprocal_link", f"job_id {str(jid)[:12]} not among loaded job records", a.file, a.line, a.id))
    for j in jobs.values():
        aid = j.data.get("application_id")
        if aid and apps and aid not in apps:
            out.append(Finding(WARNING, "reciprocal_link", f"application_id {aid[:16]} not among loaded application records", j.file, j.line, j.id))
        if aid and aid in apps and apps[aid].data.get("job_id") != j.id:
            out.append(Finding(ERROR, "reciprocal_link", "application record does not point back at this job", j.file, j.line, j.id))

    # Verdicts must name an existing job or signal.
    if jobs or signals:
        for r in records:
            if r.type == "verdict" and r.id not in jobs and r.id not in signals:
                out.append(Finding(WARNING, "verdict_target", "verdict id matches no loaded job or signal record", r.file, r.line, r.id))

    # Added check: the same id given different verdicts on the same decision date in
    # different files. The contract requires one verdict file per run; two files with
    # disagreeing rows is what a split run looks like from the outside.
    seen: dict[tuple[str, str], Record] = {}
    for r in records:
        if r.type != "verdict":
            continue
        key = (r.id, str(r.data.get("decision_date")))
        prior = seen.get(key)
        if prior and prior.file != r.file:
            if prior.data.get("verdict") != r.data.get("verdict"):
                out.append(Finding(ERROR, "verdict_conflict",
                                   f"{prior.data.get('verdict')} in {prior.file} vs {r.data.get('verdict')} here, same decision date",
                                   r.file, r.line, r.id))
            else:
                out.append(Finding(WARNING, "verdict_duplicate", f"same verdict also written in {prior.file}", r.file, r.line, r.id))
        else:
            seen[key] = r

    # Added check: one requisition under two job ids.
    by_req: dict[str, set[str]] = {}
    where: dict[str, Record] = {}
    for j in jobs.values():
        for u in [j.data.get("employer_url"), j.data.get("source_url"), *(j.data.get("url_history") or [])]:
            k = requisition_key(u)
            if k:
                by_req.setdefault(k, set()).add(j.id)
                where[j.id] = j
    for k, ids in by_req.items():
        if len(ids) > 1:
            r = where[sorted(ids)[0]]
            out.append(Finding(WARNING, "duplicate_requisition",
                               f"{k} carried under {len(ids)} job ids: " + ", ".join(i[:12] for i in sorted(ids)),
                               r.file, r.line, r.id))
    # Title-date jobs that share employer and title with a url-based job are the same
    # failure in the other direction: an enrollment record never merged with discovery.
    url_jobs = {(str(j.data.get("employer", "")).lower(), str(j.data.get("title", "")).lower()): j
                for j in jobs.values() if j.data.get("id_basis") == "url"}
    for j in jobs.values():
        if j.data.get("id_basis") == "title_date":
            twin = url_jobs.get((str(j.data.get("employer", "")).lower(), str(j.data.get("title", "")).lower()))
            if twin:
                out.append(Finding(WARNING, "duplicate_requisition",
                                   f"title_date record shares employer and title with url record {twin.id[:12]}; reconcile under section 8",
                                   j.file, j.line, j.id))
    return out


def validate(paths: Iterable[str | Path], cfg: Config | None = None) -> tuple[list[Record], list[Finding]]:
    cfg = cfg or Config()
    records, findings = load(paths)
    for r in records:
        findings += check_structure(r, cfg)
    findings += check_cross(records)
    if cfg.years_as_of is None and any(r.data.get("hold_basis") == "years_distance" for r in records):
        findings.append(Finding(WARNING, "hold_release_date", "years_as_of not supplied, so years HOLD release dates were not recomputed"))
    return records, findings
