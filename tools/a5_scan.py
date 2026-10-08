#!/usr/bin/env python3
"""Lists the "on hold" findings (A-5) in a saved evidence directory.

A-5: an ERROR-level application-log line that appears before a 4xx response
(the code logs with ``logger.error`` and then raises; a 4xx should be logged
at WARNING only). The owner's decision is that such a line does **not** fail
a test: the specification's ``evidence.ignore`` patterns tolerate it
(``(WARNING|ERROR).*<code or message>``), so the verdict stays ``pass``, but the
line is still in the saved ``diff-app-log-*`` file. This script finds those
lines so they can be recorded in the result row as ``on hold`` (inconclusive by
design, with a remark) instead of being lost behind a green run.

Reads ``<evidence-dir>/<run-id>/index.json`` (written by the hub's Python
runner when ``ATH_EVIDENCE_DIR`` is set) and, per entity, the app-log diff
files and the HTTP exchange files next to it. An entity is reported when it
has at least one ERROR line in the added app-log lines and at least one 4xx
HTTP response. Lines that look like an expected 5xx failure (traceback,
"Internal Server Error", a 3xxx code) are skipped.

Exit status is always 0 for a readable directory (a finding is not a failure);
2 for usage errors. ``--strict`` exits 1 when anything is on hold, for people
who want a gate.

Standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_ERROR_LEVEL = re.compile(r"\bERROR\b")
_EXPECTED_5XX = re.compile(r"Traceback|Internal Server Error|WEKO_SWORDSERVER_E_3\d{3}")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _status_of(exchange: Any) -> int | None:
    if not isinstance(exchange, dict):
        return None
    response = exchange.get("response")
    if isinstance(response, dict) and isinstance(response.get("status"), int):
        return response["status"]
    return None


def error_lines(diff_text: str) -> list[str]:
    """ERROR-level lines among the lines a unified diff added."""
    out = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if _ERROR_LEVEL.search(body) and not _EXPECTED_5XX.search(body):
            out.append(body.strip())
    return out


def scan_run(run_dir: Path) -> list[dict[str, Any]]:
    """Findings of one run directory (the one holding ``index.json``)."""
    index = _load_json(run_dir / "index.json")
    if not isinstance(index, dict):
        return []
    by_entity: dict[str, dict[str, Any]] = {}
    for entry in index.get("entries", []):
        entity = entry.get("entity")
        if entity is None:
            continue
        slot = by_entity.setdefault(entity, {"statuses": [], "errors": []})
        path = run_dir / entry.get("path", "")
        if entry.get("source") == "http_exchange":
            status = _status_of(_load_json(path))
            if status is not None:
                slot["statuses"].append(status)
        elif entry.get("source") == "app_log" and entry.get("role") == "diff":
            with contextlib.suppress(OSError):
                slot["errors"].extend(error_lines(path.read_text(encoding="utf-8")))
    findings = []
    for entity, slot in sorted(by_entity.items()):
        statuses_4xx = sorted({s for s in slot["statuses"] if 400 <= s < 500})
        if slot["errors"] and statuses_4xx:
            findings.append(
                {
                    "run": run_dir.name,
                    "entity": entity,
                    "status_4xx": statuses_4xx,
                    "error_lines": slot["errors"],
                }
            )
    return findings


def scan(evidence_dir: Path) -> list[dict[str, Any]]:
    """Findings of every run directory under ``evidence_dir`` (or of it, if it is one)."""
    if (evidence_dir / "index.json").is_file():
        return scan_run(evidence_dir)
    findings: list[dict[str, Any]] = []
    for child in sorted(p for p in evidence_dir.iterdir() if p.is_dir()):
        findings.extend(scan_run(child))
    return findings


def remark(finding: dict[str, Any]) -> str:
    """Remark text for the result row of an entity that passed with an A-5 finding."""
    n = len(finding["error_lines"])
    return (
        f"on hold (A-5): {n} ERROR-level app-log line(s) before 4xx "
        f"{','.join(str(s) for s in finding['status_4xx'])}; tolerated by design, "
        f"see diff-app-log in run {finding['run']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("evidence_dir", type=Path, help="ATH_EVIDENCE_DIR or one run directory")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--rows", action="store_true", help="print one remark per entity")
    parser.add_argument("--strict", action="store_true", help="exit 1 when anything is on hold")
    args = parser.parse_args(argv)
    if not args.evidence_dir.is_dir():
        print(f"not a directory: {args.evidence_dir}", file=sys.stderr)
        return 2
    findings = scan(args.evidence_dir)
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    elif args.rows:
        for f in findings:
            print(f"{f['entity']}\t{remark(f)}")
    else:
        for f in findings:
            print(f"{f['entity']}  (run {f['run']}, 4xx: {f['status_4xx']})")
            for line in f["error_lines"]:
                print(f"    {line}")
        print(f"\n{len(findings)} entity(ies) on hold (A-5)")
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
