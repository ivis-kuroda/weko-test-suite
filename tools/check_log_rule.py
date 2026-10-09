#!/usr/bin/env python3
"""Checks that every specification follows the log-judgement rule (docs/LOG-JUDGEMENT.md).

    uv run python tools/check_log_rule.py specs

The rule: the application log never fails an entity on its content. So every case and
scenario that reads the ``app_log`` channel

* carries ``evidence.ignore: [".*"]`` and nothing else in ``ignore`` (the policy's
  ``app_log: clean`` is then a presence gate only: no line, whatever its level, can fail);
* is tagged ``log:handler-line`` (it asserts, positively, that its expected handler line
  exists: an ``operation_result`` over ``OP-APP-LOG`` with a ``matches`` assertion) or
  ``log:not-judged`` (nothing about the log is asserted: a success, or a 401/403 whose
  handler logs no code), and the tag agrees with the expectations;
* when it asserts a handler line next to an ``http_status``, uses the level the design
  requires for that status (4xx WARNING, 5xx ERROR).

Exit status: 0 when every file conforms, 1 when not, 2 for usage errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from log_expect import PRESENCE_ONLY_IGNORE, is_handler_expectation, level_for_status

TAG_HANDLER = "log:handler-line"
TAG_NOT_JUDGED = "log:not-judged"
_LEVELS = re.compile(r"\\b(WARNING|ERROR)\\b")


def _statuses(expectations: list[dict[str, Any]]) -> set[int]:
    found: set[int] = set()
    for exp in expectations:
        if exp.get("kind") == "http_status":
            found.add(exp["status"])
            found.update(exp.get("alsoAccepts", []))
    return found


def _check_expectations(where: str, expectations: list[dict[str, Any]]) -> tuple[int, list[str]]:
    problems: list[str] = []
    count = 0
    statuses = _statuses(expectations)
    for exp in expectations:
        if not is_handler_expectation(exp):
            continue
        count += 1
        pattern = exp["assert"].get("pattern", "")
        try:
            re.compile(pattern)
        except re.error as exc:
            problems.append(f"{where}: the handler-line pattern is not a valid expression: {exc}")
            continue
        if exp.get("params", {}).get("since") != "{{run.startedAt}}":
            problems.append(f"{where}: the log must be read with since: '{{{{run.startedAt}}}}'")
        levels = set(_LEVELS.findall(pattern))
        if not levels:
            problems.append(f"{where}: the handler-line pattern names no level (WARNING or ERROR)")
        elif statuses:
            allowed = {level_for_status(s) for s in statuses if s >= 400}
            if not levels <= allowed:
                problems.append(
                    f"{where}: levels {sorted(levels)} do not fit the expected statuses "
                    f"{sorted(statuses)} (4xx WARNING, 5xx ERROR)"
                )
    return count, problems


def check_entity(path: Path | None, data: dict[str, Any]) -> list[str]:
    """Problems of one case or scenario file (empty when it conforms)."""
    evidence = data.get("evidence") or {}
    if "app_log" not in evidence.get("sources", []):
        return []
    problems: list[str] = []
    name = data.get("id") or (path.name if path else "?")
    if list(evidence.get("ignore", [])) != [PRESENCE_ONLY_IGNORE]:
        problems.append(
            f"{name}: evidence.ignore must be exactly [{PRESENCE_ONLY_IGNORE!r}] "
            f"(the app_log channel is never judged on content), found {evidence.get('ignore')}"
        )
    tags = set(data.get("tags", []))
    if len(tags & {TAG_HANDLER, TAG_NOT_JUDGED}) != 1:
        problems.append(f"{name}: tag it with exactly one of {TAG_HANDLER} or {TAG_NOT_JUDGED}")
    handler_count = 0
    if "steps" in data:
        for step in data["steps"]:
            count, found = _check_expectations(f"{name}/{step['id']}", step.get("expect", []))
            handler_count += count
            problems.extend(found)
    else:
        handler_count, found = _check_expectations(name, data.get("expect", []))
        problems.extend(found)
    if TAG_HANDLER in tags and handler_count == 0:
        problems.append(f"{name}: tagged {TAG_HANDLER} but asserts no handler line")
    if TAG_NOT_JUDGED in tags and handler_count:
        problems.append(f"{name}: tagged {TAG_NOT_JUDGED} but asserts a handler line")
    return problems


def check_tree(specs: Path) -> tuple[int, list[str]]:
    """Checks ``specs/cases`` and ``specs/scenarios``; returns (files checked, problems)."""
    checked = 0
    problems: list[str] = []
    for sub in ("cases", "scenarios"):
        for path in sorted((specs / sub).glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            checked += 1
            problems.extend(check_entity(path, data))
    return checked, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("specs", type=Path, help="the specs directory")
    args = parser.parse_args(argv)
    if not args.specs.is_dir():
        print(f"not a directory: {args.specs}", file=sys.stderr)
        return 2
    checked, problems = check_tree(args.specs)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"checked {checked} case/scenario file(s): {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
