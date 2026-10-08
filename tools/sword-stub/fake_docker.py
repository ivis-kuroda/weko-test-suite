#!/usr/bin/env python3
"""A fake `docker` executable for the mechanics rig (NOT a container runtime).

Put a directory containing a `docker` symlink or wrapper to this file first on
PATH, set `STUB_URL` to the running stub (for example `http://127.0.0.1:8080`),
and the commands that `plugin.yaml` and `weko_suite_ext` issue work against the
stub's state:

    docker exec -i <web> python /opt/ath-helpers/run.py <cmd>    stdin JSON -> {"ok":..,"result":..}
    docker exec -i <redis> redis-cli -n <db> GET|EXISTS|TTL|DEL|SETEX ...
    docker logs --since <ts> <container>                         app log lines (written to stderr)
    docker stop|start|restart <container>                        toggles what the stub answers

Anything else exits 1 with a docker-like message. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HELPER_ENTRY = "/opt/ath-helpers/run.py"


def _stub_url() -> str:
    url = os.environ.get("STUB_URL")
    if not url:
        sys.stderr.write("fake docker: STUB_URL is not set\n")
        raise SystemExit(125)
    return url.rstrip("/")


def _call(method: str, path: str, payload: dict | None = None) -> bytes:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(_stub_url() + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.URLError as exc:
        sys.stderr.write(f"fake docker: cannot reach the stub: {exc}\n")
        raise SystemExit(125) from exc


def _exec(argv: list[str]) -> int:
    args = [a for a in argv if a != "-i" and a != "-t" and a != "-it"]
    if not args:
        sys.stderr.write("docker exec: container name required\n")
        return 1
    container, command = args[0], args[1:]
    if len(command) >= 3 and command[0].startswith("python") and command[1] == HELPER_ENTRY:
        text = sys.stdin.read() if command[2] != "list" else ""
        try:
            params = json.loads(text) if text.strip() else {}
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": {"type": "InvalidJson", "message": str(exc)}}))
            return 0
        reply = _call("POST", "/__stub__/helper", {"cmd": command[2], "params": params})
        sys.stdout.write(reply.decode().strip() + "\n")
        return 0
    if command and command[0] == "redis-cli":
        rest = command[1:]
        if rest[:1] == ["-n"]:
            rest = rest[2:]
        reply = json.loads(
            _call(
                "POST",
                "/__stub__/docker",
                {"action": "redis", "container": container, "args": rest},
            )
        )
        sys.stdout.write(reply.get("stdout", ""))
        sys.stderr.write(reply.get("stderr", ""))
        return int(reply.get("exit", 0))
    sys.stderr.write(f"fake docker: unsupported exec {command!r}\n")
    return 1


def _logs(argv: list[str]) -> int:
    since = None
    rest = list(argv)
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag == "--since" and rest:
            since = rest.pop(0)
    if not rest:
        sys.stderr.write("docker logs: container name required\n")
        return 1
    query = {"container": rest[-1]}
    if since:
        query["since"] = since
    text = _call("GET", "/__stub__/logs?" + urllib.parse.urlencode(query)).decode()
    sys.stderr.write(text)  # `docker logs` replays the container's stderr on stderr
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("usage: docker COMMAND (fake: exec, logs, stop, start, restart)\n")
        return 1
    command, rest = argv[0], argv[1:]
    if command == "exec":
        return _exec(rest)
    if command == "logs":
        return _logs(rest)
    if command in ("stop", "start", "restart") and rest:
        reply = json.loads(
            _call("POST", "/__stub__/docker", {"action": command, "container": rest[-1]})
        )
        sys.stdout.write(reply.get("stdout", ""))
        sys.stderr.write(reply.get("stderr", ""))
        return int(reply.get("exit", 0))
    sys.stderr.write(f"fake docker: unsupported command {command!r}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
