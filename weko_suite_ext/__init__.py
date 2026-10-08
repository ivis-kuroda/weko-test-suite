"""Host-side extension handlers for the WEKO3 plugin (`plugin.yaml`).

The hub calls `helper(params, context)` for every `OP-HELPER` operation.
WEKO3 runs inside docker-compose and its state (users, OAuth tokens, SWORD
clients, records, DB snapshots, fault injection) can only be changed from
inside the web container with the application's own models. The scripts for
that live in `helpers/` and run on the container's Python 3.6; this module is
the host-side half: it ships a JSON request to
`python /opt/ath-helpers/run.py <cmd>` through `docker exec -i` and hands the
JSON answer back to the hub.

Nothing here needs docker to be tested: the docker call goes through a
`Runner` that tests replace with `set_runner`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from typing import Any

from agentic_test_hub_runner import ExecutionContext, ExecutionResult

DEFAULT_CONTAINER = "weko-web-1"
"""Container name used when `WEKO_WEB_CONTAINER` is not set."""

HELPER_ENTRY = "/opt/ath-helpers/run.py"
"""Where the helper scripts are mounted inside the web container."""

DEFAULT_TIMEOUT_S = 120.0

_CMD_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

Runner = Callable[[list[str], str, float], "tuple[int, str, str]"]
"""`runner(argv, stdin_text, timeout_s) -> (returncode, stdout, stderr)`."""


def docker_runner(argv: list[str], stdin: str, timeout: float) -> tuple[int, str, str]:
    """Runs `argv` as a process (never through a shell) and captures its output."""
    completed = subprocess.run(
        argv, input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )
    return completed.returncode, completed.stdout, completed.stderr


_runner: Runner = docker_runner


def set_runner(runner: Runner | None) -> Runner:
    """Replaces the process runner (for tests); `None` restores docker.

    @returns The runner that was active before, so a test can put it back.
    """
    global _runner
    previous = _runner
    _runner = runner or docker_runner
    return previous


def _env(context: ExecutionContext | None) -> Mapping[str, str]:
    scoped = (context.scopes.get("env") if context is not None else None) or {}
    return {**os.environ, **scoped}


def container_name(context: ExecutionContext | None = None) -> str:
    """The web container the helpers run in (`WEKO_WEB_CONTAINER`)."""
    return _env(context).get("WEKO_WEB_CONTAINER") or DEFAULT_CONTAINER


def build_argv(container: str, cmd: str) -> list[str]:
    """The docker command line for one helper command."""
    return ["docker", "exec", "-i", container, "python", HELPER_ENTRY, cmd]


def _failed(operation: str, started: float, message: str, **extra: Any) -> ExecutionResult:
    return ExecutionResult(
        operation=operation,
        ok=False,
        duration_ms=(time.monotonic() - started) * 1000,
        failure=message,
        **extra,
    )


def helper(params: dict[str, Any], context: ExecutionContext | None = None) -> ExecutionResult:
    """Runs one in-container helper command.

    Params:
        cmd: helper command name, e.g. `snapshot` (`list` lists them).
        params: JSON object as a string, sent on stdin. Empty or absent means `{}`.

    `ok` means the helper ran and answered with JSON. Whether the helper
    itself succeeded is in `body.ok` (and `body.result` / `body.error`), so a
    case can assert on a helper failure as well as on a success. `stdout` is
    the raw answer, kept for evidence diffs.
    """
    started = time.monotonic()
    cmd = params.get("cmd")
    operation = f"helper {cmd}"
    if not isinstance(cmd, str) or not _CMD_RE.match(cmd):
        return _failed(operation, started, f"invalid helper command name: {cmd!r}")

    payload = params.get("params")
    if payload is None or payload == "":
        payload = "{}"
    elif not isinstance(payload, str):  # tolerate an already-structured value
        payload = json.dumps(payload)
    try:
        json.loads(payload)
    except ValueError as exc:
        return _failed(operation, started, f"params is not valid JSON: {exc}")

    argv = build_argv(container_name(context), cmd)
    try:
        code, out, err = _runner(argv, payload, DEFAULT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return _failed(operation, started, f"could not run docker: {exc}")

    if code != 0:
        return _failed(
            operation,
            started,
            f"docker exec exited with {code}: {err.strip()[:500]}",
            exit_code=code,
            stdout=out,
            stderr=err,
        )
    try:
        body = json.loads(out)
    except ValueError:
        return _failed(
            operation,
            started,
            "helper did not answer with JSON",
            exit_code=code,
            stdout=out,
            stderr=err,
        )
    return ExecutionResult(
        operation=operation,
        ok=True,
        duration_ms=(time.monotonic() - started) * 1000,
        exit_code=code,
        stdout=out,
        stderr=err,
        body=body,
    )
