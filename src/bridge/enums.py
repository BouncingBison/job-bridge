"""Closed enumerations from the Bridge Data Contract, schema v9, section 9.

The contract states the current schema version in exactly one place, and so does this
module: SCHEMA_VERSION below. Everything else imports it.
"""

SCHEMA_VERSION = 9

RECORD_TYPE = {"job", "signal", "application", "verdict", "source"}
SOURCE_KIND = {"ats_api", "job_board", "company_page", "vc_portfolio", "ecosystem"}
EVENT = {"new", "changed", "modified", "closed", "reappeared"}
VERDICT = {"SEND", "CHEAP_SHOT", "READ", "WATCH", "KILL", "HOLD"}

CAUSE = {
    "tool_gate", "concept_gate", "technical_gate", "years_gate",
    "people_management_gate", "domain_gate", "deliverable_gate", "quota_gate",
    "geography_gate", "sequencing", "comp_floor", "provenance",
    "evidence_coverage", "pedigree_gate",
}

# Section 10, structural override scope. These are the only gates a disclosure can clear.
OVERRIDABLE = {"tool_gate", "concept_gate", "domain_gate"}

# Every cause that represents a gate firing. evidence_coverage and provenance are
# outcomes of reading, not gates, and sequencing is procedural.
GATES = CAUSE - {"evidence_coverage", "provenance"}
NON_OVERRIDABLE_GATES = GATES - OVERRIDABLE

OVERRIDE_BASIS = {"apac_in_region", "eor_structure", "singapore_timezone"}
HOLD_BASIS = {"sequencing", "years_distance"}
HOLD_RELEASE_TYPE = {"date", "event", "either"}
URL_SOURCE = {"posting", "confirmation_email", "posting_at_submission", "none"}
ID_BASIS = {"url", "title_date"}
SOURCE_OF_DISCOVERY = {"bridge", "feed_sweep", "research_conversation", "manual", "referral"}
APP_STATUS = {"open", "rejected", "withdrawn", "interviewing", "offer", "closed_no_response"}
SIGNAL_KIND = {"fund_close", "funding_round", "venture_studio", "expansion", "acquisition", "outreach_lead"}
MOVE_TYPE = {"staffing", "expansion", "consolidation", "cost_relocation", "function_creation"}
HYPOTHESIS_STATUS = {"untested", "supported", "confirmed", "falsified"}
VACANCY_CONFIRMED = {"true", "false", "unknown"}
QUEUE_SHAPE = {"door", "list", "unknown"}
QUEUE_SIGNALS = {
    "reappeared", "long_open", "first_of_kind", "intersection", "small_org",
    "unposted", "large_pool", "large_employer", "pedigree_preferred",
}
# Section 10, door evidence: a door must name at least one of these.
DOOR_SIGNALS = {"reappeared", "long_open", "first_of_kind", "intersection", "small_org", "unposted"}
