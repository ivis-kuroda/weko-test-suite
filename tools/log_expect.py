#!/usr/bin/env python3
"""Builds the log expectations of the SWORD specifications (one place, one rule).

WEKO's internals log errors and stack traces for harmless and critical conditions
alike, also far outside the scope of a change, so the application log is never
judged on "no ERROR line" (owner decision 2026-10-09, docs/LOG-JUDGEMENT.md).
A case instead proves, positively, that the log carries the expected line
*from the right place at the right level*:

* the right place is the blueprint's error handler
  (``handle_weko_swordserver_exception``; ``handle_ratelimit`` for 429), whose line
  has the shape ``[{code}] {method} {path}: {message}`` (detailed design 2.2
  processing step 3). The ``current_app.logger.error(...)`` calls made before an
  exception is raised do not have that shape, so matching the shape cannot be
  satisfied by them or by unrelated noise;
* the right level is set by the HTTP status (basic design 5.4): 4xx is WARNING;
  500, 501 and 503 are ERROR, and a 503 that propagates by type (the DB, Redis or
  Elasticsearch dependency handler) carries a stack trace (spec C-5xx-3).

The expectation is an ``operation_result`` over ``OP-APP-LOG`` (the web container log
since ``{{run.startedAt}}``) with a ``matches`` assertion; the hub judges it with
``re.search``. Every other line of the log is ignored by the verdict and kept in the
saved evidence (``tools/log_remarks.py`` lists the out-of-scope ERROR lines).

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

LOG_OPERATION = "OP-APP-LOG"
"""Plugin operation reading the web container log (``plugin.yaml``)."""

PRESENCE_ONLY_IGNORE = ".*"
"""The ``evidence.ignore`` pattern every entity carries: with the policy's
``app_log: clean`` it makes the channel a presence gate (the collector must have
run) that no line can fail."""

CODE_PREFIX = "WEKO_SWORDSERVER_E_"

# Operation id -> (HTTP method, path regex as the handler logs it; no query string).
ENDPOINTS: dict[str, tuple[str, str]] = {
    "OP-SWORD-GET-SERVICE-DOC": ("GET", "/sword/service-document"),
    "OP-SWORD-GET-SERVICE-DOC-UNAUTH": ("GET", "/sword/service-document"),
    "OP-SWORD-POST": ("POST", "/sword/service-document"),
    "OP-SWORD-POST-UNAUTH": ("POST", "/sword/service-document"),
    "OP-SWORD-POST-NOFILE": ("POST", "/sword/service-document"),
    "OP-SWORD-GET-DEPOSIT": ("GET", r"/sword/deposit/[^\s:]+"),
    "OP-SWORD-GET-DEPOSIT-UNAUTH": ("GET", r"/sword/deposit/[^\s:]+"),
    "OP-SWORD-PUT": ("PUT", r"/sword/deposit/[^\s:]+"),
    "OP-SWORD-PUT-UNAUTH": ("PUT", r"/sword/deposit/[^\s:]+"),
    "OP-SWORD-PUT-NOFILE": ("PUT", r"/sword/deposit/[^\s:]+"),
    "OP-SWORD-DELETE": ("DELETE", r"/sword/deposit/[^\s:]+"),
    "OP-SWORD-DELETE-UNAUTH": ("DELETE", r"/sword/deposit/[^\s:]+"),
}

TRACEBACK = r"Traceback \(most recent call last\):"


def level_for_status(status: int) -> str:
    """Log level the design requires for a response status (basic design 5.4)."""
    if status >= 500:
        return "ERROR"
    if 400 <= status < 500:
        return "WARNING"
    raise ValueError(f"no handler line is expected for status {status}")


@dataclass(frozen=True)
class Variant:
    """One acceptable (code, status) outcome of a step.

    ``code`` is the digits of the code or a regular-expression fragment for a band
    (``13\\d\\d``, ``140[4-7]``), ``status`` the HTTP status it comes with (this fixes
    the level), ``trace`` demands a stack trace attached to the handler line.
    """

    code: str
    status: int
    trace: bool = False


def handler_line_regex(variant: Variant, method: str, path: str) -> str:
    """Regular expression (for ``re.search``) of one handler line.

    The level must precede the bracketed code on the same line; ``[^\\n]`` keeps the
    whole match on one log line. The code may be written with or without the
    ``WEKO_SWORDSERVER_E_`` prefix, because the design shows the bracket content as
    ``{code}`` (digits) while the log message of v2.2.0 uses the prefix.
    """
    level = level_for_status(variant.status)
    line = rf"\b{level}\b[^\n]*\[(?:{CODE_PREFIX})?{variant.code}\] {method} {path}:"
    if variant.trace:
        line += rf"[^\n]*\n{TRACEBACK}"
    return line


def handler_pattern(variants: list[Variant], method: str, path: str) -> str:
    """Pattern accepting any of ``variants`` (one handler line each)."""
    if not variants:
        raise ValueError("at least one variant is required")
    parts = [handler_line_regex(v, method, path) for v in variants]
    return parts[0] if len(parts) == 1 else "(?:" + "|".join(parts) + ")"


def handler_expectation(variants: list[Variant], operation: str) -> dict:
    """The ``operation_result`` expectation for a step that calls ``operation``."""
    if operation not in ENDPOINTS:
        raise KeyError(f"no endpoint known for {operation}")
    method, path = ENDPOINTS[operation]
    return {
        "kind": "operation_result",
        "operation": LOG_OPERATION,
        "params": {"since": "{{run.startedAt}}"},
        "assert": {"kind": "matches", "pattern": handler_pattern(variants, method, path)},
        "viewpoints": [],
    }


def is_handler_expectation(expectation: dict) -> bool:
    """True for an expectation built by :func:`handler_expectation`."""
    return (
        expectation.get("kind") == "operation_result"
        and expectation.get("operation") == LOG_OPERATION
        and expectation.get("assert", {}).get("kind") == "matches"
    )
