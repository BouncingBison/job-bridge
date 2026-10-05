# job-bridge

Tooling for a two-agent job search pipeline. One agent casts wide and writes what it finds; the other triages and writes verdicts back. They share a data contract, and this repo enforces it in code.

The contract grew out of real failures, and each one is encoded here as a check:

| Failure seen in practice | What this repo does |
|---|---|
| A live posting was marked closed because a fetch failed. It happened twice | `bridge check` returns UNKNOWN on any failed, blocked or 404 fetch. Only positive closure text on the employer's own page counts as closed |
| A verdict named an overridable gate while a hard gate had also fired, so a dead row looked worth ten minutes | The legality matrix checks every cause that fired, not only the one that was named |
| One requisition reached through two URL shapes arrived as two records | `requisition_key` maps every Greenhouse, Lever and Ashby URL shape for a posting to one key |
| An application enrolled from a confirmation email never merged with the record discovery created | Title-date records that share employer and title with a URL record are flagged for reconciliation |
| A run split across helpers wrote two verdict files that disagreed | Same id, same decision date, different verdict across files is an error |

## Install

```
pip install -e ".[test]"
pytest
```

## Use

Validate run files. Exit status is 1 on any error, so a scheduled run can refuse to upload a file that fails:

```
bridge validate 2026-10-02_*_verdicts.jsonl 2026-10-04_*_bridge.jsonl
bridge validate *.jsonl --errors-only
bridge validate *.jsonl --years-as-of 2026-01-01   # recompute years-HOLD release dates
```

Read postings from the employer's own ATS:

```
bridge check https://job-boards.greenhouse.io/<board>/jobs/<id> https://jobs.lever.co/<board>/<uuid>
```

## What gets checked

1. **Structure.** JSON parses, `schema_version` is current, required fields exist (nullable fields must be present even when null), every enum sits inside its closed list, ids are well formed for their record type.
2. **The legality matrix.** Eight legal rows for job and verdict records. A row that matches none of them is invalid by construction.
3. **Cross-record integrity.** Reciprocal application links, the post-application flag recomputed rather than trusted, URL and id agreement, door evidence, years arithmetic, and the conflict and duplicate checks above.

Records from earlier schema versions are reported as `legacy`, never rejected. Fields outside the contract are reported as warnings, because a field the contract does not name is a field nothing on the other side will read.

## Layout

```
src/bridge/enums.py      closed enumerations; the schema version lives here and only here
src/bridge/ids.py        normalization, canonical URLs, ids, requisition keys
src/bridge/validate.py   structure, matrix, cross-record checks
src/bridge/ats.py        Greenhouse, Lever and Ashby readers
src/bridge/cli.py        command line
tests/                   synthetic fixtures only
```

## Open items

- **Hash layout.** The contract specifies hash inputs but not byte layout. Ids computed here use sha256 over normalized fields joined by `|`. Until that matches the writing side, recomputed ids are informational and never overwrite existing ones.
- **Verdict targets.** A verdict whose job record sits in a file that was not loaded is reported as a warning. Load the matching bridge files to silence it.
- **Next.** Schema-version drift detection for the writing agent, a source-cadence calculator for the `source` record type, and a Drive reader so validation runs before upload rather than after.

No personal data lives in this repository. Run files, profiles and rules stay in the private bridge folder.
