"""Tooling for a two-agent job-search bridge: a data contract validator, stable IDs,
and employer-ATS posting reads that never mistake a failed fetch for a closure."""

from .enums import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
__version__ = "0.1.0"
