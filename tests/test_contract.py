"""Matrix and integrity tests. Every fixture is synthetic: employers are invented and no
record describes a real person or application."""

import json
from datetime import date

import pytest

from bridge import ats, ids
from bridge.validate import ERROR, Config, Record, check_cross, check_matrix, validate

H = "a" * 64


def job(**over):
    base = {
        "schema_version": 9, "id": H, "record_type": "job", "detected_date": "2026-10-01",
        "source": "test", "source_url": "https://job-boards.greenhouse.io/acme/jobs/1",
        "event": "new", "employer": "Acme", "title": "Strategy Manager", "location": "Remote",
        "employer_url": "https://job-boards.greenhouse.io/acme/jobs/1", "url_source": "posting",
        "id_basis": "url", "verdict": "SEND", "causes_all": [], "queue_shape": "unknown",
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not DROP}


DROP = object()


def errors(d, cfg=None):
    return [f for f in check_matrix(Record(d, "t.jsonl", 1), cfg or Config()) if f.severity == ERROR]


# ---- legal rows -------------------------------------------------------------

LEGAL = {
    "send": job(),
    "cheap_evidence": job(verdict="CHEAP_SHOT", cause_primary="evidence_coverage", cause_detail="2 of 5 anchored"),
    "cheap_override": job(verdict="CHEAP_SHOT", cause_primary="tool_gate", causes_all=["tool_gate", "domain_gate"],
                          override_applied=True, override_basis="apac_in_region"),
    "kill_tool": job(verdict="KILL", cause_primary="tool_gate", causes_all=["tool_gate"]),
    "kill_years": job(verdict="KILL", cause_primary="years_gate", causes_all=["years_gate"],
                      years_required=10, years_held=7, short_by=3),
    "hold_seq": job(verdict="HOLD", cause_primary="sequencing", causes_all=["sequencing"], hold_basis="sequencing",
                    hold_set_date="2026-10-01", hold_release_type="date", hold_release_date="2026-10-11"),
    "hold_years": job(verdict="HOLD", cause_primary="years_gate", causes_all=["years_gate"], override_applied=False,
                      years_required=10, years_held=8, short_by=2, hold_basis="years_distance",
                      hold_set_date="2026-10-01", hold_release_type="either",
                      hold_release_date="2026-01-01", hold_release_event="years requirement lowered"),
    "read_provenance": job(verdict="READ", cause_primary="provenance", causes_all=["provenance"]),
    "read_evidence": job(verdict="READ", cause_primary="evidence_coverage"),
    "watch": job(verdict="WATCH", cause_primary="evidence_coverage"),
    "door": job(queue_shape="door", queue_signals=["first_of_kind", "large_employer"]),
}


@pytest.mark.parametrize("name", LEGAL)
def test_legal_rows_pass(name):
    assert errors(LEGAL[name]) == []


# ---- illegal rows -----------------------------------------------------------

def test_v7_example_cheap_shot_hiding_a_hard_gate():
    # The contract's own example: legal under v6, invalid under v7.
    d = job(verdict="CHEAP_SHOT", cause_primary="tool_gate", causes_all=["tool_gate", "technical_gate"],
            override_applied=True, override_basis="apac_in_region")
    msgs = " ".join(f.message for f in errors(d))
    assert "non-overridable" in msgs


def test_kill_must_name_the_hard_gate():
    d = job(verdict="KILL", cause_primary="tool_gate", causes_all=["tool_gate", "technical_gate"])
    assert any("must name one of them" in f.message for f in errors(d))


def test_thin_evidence_never_kills():
    assert errors(job(verdict="KILL", cause_primary="evidence_coverage"))


def test_send_with_a_cause_is_invalid():
    assert errors(job(cause_primary="tool_gate", causes_all=["tool_gate"]))


def test_years_hold_needs_explicit_false():
    d = dict(LEGAL["hold_years"])
    del d["override_applied"]
    assert any("explicit" in f.message for f in errors(d))


def test_years_hold_with_second_gate_is_a_kill():
    d = dict(LEGAL["hold_years"], causes_all=["years_gate", "people_management_gate"])
    assert errors(d)


def test_hold_release_date_recomputed():
    cfg = Config(years_as_of=date(2026, 1, 1))
    assert errors(LEGAL["hold_years"], cfg) == []  # short_by 2 -> +0 years
    bad = dict(LEGAL["hold_years"], hold_release_date="2027-06-01")
    assert any(f.rule == "hold_release_date" for f in errors(bad, cfg))


def test_door_needs_door_signal():
    assert errors(job(queue_shape="door", queue_signals=["large_employer"]))


def test_override_basis_without_override():
    assert errors(job(verdict="KILL", cause_primary="tool_gate", causes_all=["tool_gate"], override_basis="eor_structure"))


def test_read_with_gate_is_invalid():
    assert errors(job(verdict="READ", cause_primary="tool_gate", causes_all=["tool_gate"]))


def test_short_by_arithmetic():
    d = dict(LEGAL["kill_years"], short_by=2)
    assert any("short_by" in f.message for f in errors(d))


# ---- events and cross-record ------------------------------------------------

def test_modified_cannot_carry_verdict_change(tmp_path):
    d = job(event="modified", change_note=[{"field": "x", "before": "a", "after": "b"}], edit_count=1,
            verdict_before="SEND", verdict_after="SEND")
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(d))
    _, findings = validate([p])
    assert any(f.rule == "modified_event" for f in findings)


def test_post_application_flag_is_recomputed(tmp_path):
    d = job(event="modified", change_note=[{"field": "x", "before": "a", "after": "b"}], edit_count=1,
            application_id=None, changed_post_application=True)
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(d))
    _, findings = validate([p])
    assert any(f.rule == "post_application" for f in findings)


def test_conflicting_verdicts_across_files(tmp_path):
    v1 = {"schema_version": 9, "id": H, "record_type": "verdict", "detected_date": "2026-10-02", "source": "t",
          "source_url": None, "verdict": "SEND", "decision_date": "2026-10-02", "causes_all": [], "queue_shape": "list"}
    v2 = dict(v1, verdict="CHEAP_SHOT", cause_primary="evidence_coverage", cause_detail="2 of 5")
    a, b = tmp_path / "a_verdicts.jsonl", tmp_path / "b_verdicts.jsonl"
    a.write_text(json.dumps(v1))
    b.write_text(json.dumps(v2))
    _, findings = validate([a, b])
    assert any(f.rule == "verdict_conflict" for f in findings)


def test_same_requisition_two_ids():
    j1 = job(id="b" * 64, employer_url="https://job-boards.greenhouse.io/acme/jobs/77")
    j2 = job(id="c" * 64, employer_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs/77")
    out = check_cross([Record(j1, "a", 1), Record(j2, "b", 1)])
    assert any(f.rule == "duplicate_requisition" for f in out)


def test_title_date_twin_of_url_record():
    j1 = job(id="b" * 64)
    j2 = job(id="c" * 64, id_basis="title_date", url_source="none", employer_url=None, source_url=None)
    out = check_cross([Record(j1, "a", 1), Record(j2, "b", 1)])
    assert any("title_date record shares" in f.message for f in out)


def test_legacy_versions_are_reported_not_rejected(tmp_path):
    p = tmp_path / "old.jsonl"
    p.write_text(json.dumps(job(schema_version=7)))
    _, findings = validate([p])
    assert any(f.rule == "schema_version" and f.severity == "legacy" for f in findings)


# ---- ids and ATS ------------------------------------------------------------

def test_requisition_keys_agree_across_url_shapes():
    keys = {ids.requisition_key(u) for u in [
        "https://job-boards.greenhouse.io/acmeco/jobs/123",
        "https://boards.greenhouse.io/acmeco/jobs/123?gh_src=abc",
        "https://boards-api.greenhouse.io/v1/boards/acmeco/jobs/123",
    ]}
    assert keys == {"greenhouse:acmeco:123"}


def test_canonical_url_drops_tracking_keeps_jid():
    u = ids.canonical_url("HTTPS://Example.com/careers/?gh_jid=55&utm_source=x#apply")
    assert u == "https://example.com/careers?gh_jid=55"


def test_job_id_basis():
    _, basis = ids.job_id("Acme", "Analyst", None, "2026-10-01")
    assert basis == "title_date"
    _, basis = ids.job_id("Acme", "Analyst", "https://jobs.lever.co/acme/" + "1" * 8 + "-1111-1111-1111-" + "1" * 12, "2026-10-01")
    assert basis == "url"


def test_failed_fetch_is_unknown_never_closed(monkeypatch):
    monkeypatch.setattr(ats, "_get", lambda url: None)
    p = ats.fetch("https://job-boards.greenhouse.io/acme/jobs/1")
    assert p.status == "unknown"


def test_404_is_unknown(monkeypatch):
    class R:
        status_code = 404
    monkeypatch.setattr(ats, "_get", lambda url: R())
    assert ats.fetch("https://job-boards.greenhouse.io/acme/jobs/1").status == "unknown"


def test_closure_needs_positive_evidence():
    assert ats.closure_evidence("Sorry, this job has expired")
    assert not ats.closure_evidence("Page could not be loaded")
