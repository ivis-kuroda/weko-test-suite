#!/usr/bin/env python3
"""Rig-only workaround for a hub finding; see docs/stub.md, finding F-1.

The Python runtime judges `app_log: clean` but never reads a case's
`evidence.ignore` patterns: `run_case` / `run_scenario` take them only from
`RunOptions(observe=ObserveOptions(ignore=...))`, and the generated test passes
no options. Without this patch every error case fails on its own expected
ERROR line. The patch hands the spec's own `evidence.ignore` to the runner.

    python patch_generated.py tests/generated/*.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

IMPORT = (
    "from agentic_test_hub_runner.evidence import ObserveOptions\n"
    "from agentic_test_hub_runner.run_case import RunOptions\n"
)
OPTIONS = (
    "RunOptions(observe=ObserveOptions("
    'ignore=list(({0}.get("evidence") or {{}}).get("ignore", []))))'
)


def patch(text: str) -> str:
    if "ObserveOptions" in text:
        return text
    out = text.replace("import weko_suite_ext as", IMPORT + "import weko_suite_ext as", 1)
    out = re.sub(
        r"run_case\(TEST_CASE, RESOLVED, ACTION_PARAMS, registry, context\)",
        "run_case(TEST_CASE, RESOLVED, ACTION_PARAMS, registry, context, "
        + OPTIONS.format("TEST_CASE")
        + ")",
        out,
    )
    out = re.sub(
        r"run_scenario\(SCENARIO, registry, context\)",
        "run_scenario(SCENARIO, registry, context, " + OPTIONS.format("SCENARIO") + ")",
        out,
    )
    return out


def main(paths: list[str]) -> int:
    for name in paths:
        path = Path(name)
        path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
