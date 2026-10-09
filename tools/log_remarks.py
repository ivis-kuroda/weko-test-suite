#!/usr/bin/env python3
"""Lists the out-of-scope ERROR lines of a saved evidence directory, as remarks.

The application log never decides a verdict (docs/LOG-JUDGEMENT.md): WEKO writes
ERROR lines and stack traces for harmless and critical conditions alike, also far
outside what a change touched. A case passes or fails on its own expectations, among
them the presence of the expected handler line. Whatever else the log holds stays in
the saved ``diff-app-log-*`` file; this script summarises it so a human can put it in
the result row's remark column instead of losing it behind a green run.

Per entity (case or scenario) it reports the ERROR-level lines added to the log during
the run, except the handler lines of a 5xx response (``[3108] GET /sword/...: ...``,
which that response is expected to log at ERROR), and the number of stack traces. When
the entity also received a 4xx response, the ERROR lines are marked ``A-5 candidate``:
spec v4.2 4.5 A-5 is an ERROR line logged before a 4xx is raised (basic design 5.4: 4xx
is WARNING only). It is a remark for the implementation team, never a failure.

Reads ``<evidence-dir>/<run-id>/index.json`` (written by the hub's Python runner when
``ATH_EVIDENCE_DIR`` is set) and, per entity, the app-log diff files and the HTTP
exchange files next to it. The exit status is 0 for a readable directory (2 for usage
errors); ``--strict`` exits 1 when there is any remark, for people who want a gate.

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
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)")
_HANDLER_LINE = re.compile(r"\[(?:WEKO_SWORDSERVER_E_)?\d{4}\] [A-Z]+ /sword/")


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


def added_lines(diff_text: str) -> list[str]:
    """The lines a unified diff added (the lines logged during the run)."""
    return [
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def summarise_log(added: list[str], has_5xx: bool) -> dict[str, Any]:
    """ERROR-level lines and stack traces among ``added``.

    The ERROR handler line of a 5xx response is the expected one and is not reported.
    """
    errors = []
    for line in added:
        body = line.strip()
        if not _ERROR_LEVEL.search(body):
            continue
        if has_5xx and _HANDLER_LINE.search(body):
            continue
        errors.append(body)
    return {"error_lines": errors, "traces": sum(1 for line in added if _TRACEBACK.search(line))}


def scan_run(run_dir: Path) -> list[dict[str, Any]]:
    """Remarks of one run directory (the one holding ``index.json``)."""
    index = _load_json(run_dir / "index.json")
    if not isinstance(index, dict):
        return []
    by_entity: dict[str, dict[str, Any]] = {}
    for entry in index.get("entries", []):
        entity = entry.get("entity")
        if entity is None:
            continue
        slot = by_entity.setdefault(entity, {"statuses": [], "added": []})
        path = run_dir / entry.get("path", "")
        if entry.get("source") == "http_exchange":
            status = _status_of(_load_json(path))
            if status is not None:
                slot["statuses"].append(status)
        elif entry.get("source") == "app_log" and entry.get("role") == "diff":
            with contextlib.suppress(OSError):
                slot["added"].extend(added_lines(path.read_text(encoding="utf-8")))
    remarks = []
    for entity, slot in sorted(by_entity.items()):
        statuses = sorted(set(slot["statuses"]))
        summary = summarise_log(slot["added"], any(s >= 500 for s in statuses))
        if summary["error_lines"] or summary["traces"]:
            remarks.append(
                {
                    "run": run_dir.name,
                    "entity": entity,
                    "statuses": statuses,
                    "a5_candidate": bool(summary["error_lines"])
                    and any(400 <= s < 500 for s in statuses),
                    **summary,
                }
            )
    return remarks


def scan(evidence_dir: Path) -> list[dict[str, Any]]:
    """Remarks of every run directory under ``evidence_dir`` (or of it, if it is one)."""
    if (evidence_dir / "index.json").is_file():
        return scan_run(evidence_dir)
    found: list[dict[str, Any]] = []
    for child in sorted(p for p in evidence_dir.iterdir() if p.is_dir()):
        found.extend(scan_run(child))
    return found


def remark(item: dict[str, Any]) -> str:
    """Remark text for the result row of an entity whose log held out-of-scope lines."""
    n = len(item["error_lines"])
    text = (
        f"out-of-scope log lines (not part of the verdict): {n} ERROR line(s), "
        f"{item['traces']} stack trace(s)"
    )
    if item["a5_candidate"]:
        codes = ",".join(str(s) for s in item["statuses"] if 400 <= s < 500)
        text += f"; A-5 candidate: ERROR logged with 4xx {codes}"
    return f"{text}; see diff-app-log in run {item['run']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("evidence_dir", type=Path, help="ATH_EVIDENCE_DIR or one run directory")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--rows", action="store_true", help="print one remark per entity")
    parser.add_argument("--strict", action="store_true", help="exit 1 when there is any remark")
    args = parser.parse_args(argv)
    if not args.evidence_dir.is_dir():
        print(f"not a directory: {args.evidence_dir}", file=sys.stderr)
        return 2
    found = scan(args.evidence_dir)
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    elif args.rows:
        for item in found:
            print(f"{item['entity']}\t{remark(item)}")
    else:
        for item in found:
            flag = "  [A-5 candidate]" if item["a5_candidate"] else ""
            print(f"{item['entity']}  (run {item['run']}, statuses: {item['statuses']}){flag}")
            for line in item["error_lines"]:
                print(f"    {line}")
        print(
            f"\n{len(found)} entity(ies) with out-of-scope ERROR lines or stack traces "
            "(remarks only)"
        )
    return 1 if (args.strict and found) else 0


if __name__ == "__main__":
    sys.exit(main())
