"""Command line.

    bridge validate FILE [FILE ...] [--years-as-of YYYY-MM-DD] [--errors-only]
    bridge check URL [URL ...]
    bridge id job EMPLOYER TITLE URL_OR_DASH DETECTED_DATE

Exit status is 1 when any error-level finding exists, so a scheduled run can refuse to
upload a file that fails the contract.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date

from . import ats, ids
from .validate import ERROR, Config, validate


def _cmd_validate(a) -> int:
    cfg = Config(years_as_of=date.fromisoformat(a.years_as_of) if a.years_as_of else None,
                 warn_unknown_fields=not a.no_unknown)
    records, findings = validate(a.files, cfg)
    shown = [f for f in findings if f.severity == ERROR] if a.errors_only else findings
    for f in sorted(shown, key=lambda f: (f.severity != ERROR, f.file, f.line)):
        print(f)
    counts = Counter(f.severity for f in findings)
    types = Counter(r.type for r in records)
    print(f"\n{len(records)} records ({', '.join(f'{v} {k}' for k, v in sorted(types.items()))}) in {len(a.files)} file(s): "
          f"{counts.get('error', 0)} errors, {counts.get('warning', 0)} warnings, {counts.get('legacy', 0)} legacy")
    return 1 if counts.get(ERROR) else 0


def _cmd_check(a) -> int:
    for url in a.urls:
        p = ats.fetch(url)
        print(f"{p.status.upper():8} {p.key or '-':45} {p.title or ''}")
        print(f"         reason: {p.reason}")
        if p.status == "open":
            print(f"         location: {p.location}  published: {p.first_published}  updated: {p.updated_at}  pay: {p.pay_text}")
    return 0


def _cmd_id(a) -> int:
    url = None if a.url == "-" else a.url
    value, basis = ids.job_id(a.employer, a.title, url, a.detected_date)
    print(f"{value}  id_basis={basis}  requisition_key={ids.requisition_key(url)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bridge", description="Bridge Data Contract v9 tooling")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="validate JSONL run files against the contract")
    v.add_argument("files", nargs="+")
    v.add_argument("--years-as-of", help="profile years_as_of, enables HOLD release date recomputation")
    v.add_argument("--errors-only", action="store_true")
    v.add_argument("--no-unknown", action="store_true", help="suppress warnings for fields outside the contract")
    v.set_defaults(func=_cmd_validate)

    c = sub.add_parser("check", help="read postings from the employer's ATS; failures are UNKNOWN")
    c.add_argument("urls", nargs="+")
    c.set_defaults(func=_cmd_check)

    i = sub.add_parser("id", help="compute a job id")
    i.add_argument("kind", choices=["job"])
    i.add_argument("employer")
    i.add_argument("title")
    i.add_argument("url")
    i.add_argument("detected_date")
    i.set_defaults(func=_cmd_id)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
