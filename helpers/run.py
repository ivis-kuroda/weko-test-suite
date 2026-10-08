"""Entry point: ``python /opt/ath-helpers/run.py <cmd>`` with JSON on stdin.

Prints exactly one JSON object on stdout. Exit code is 0 even for
``ok: false``; non-zero only for crashes outside the contract.
"""

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import contract  # noqa: E402
import registry  # noqa: E402


def execute(cmd, params, app_factory=None):
    """Run one command and return its envelope (never raises)."""
    try:
        if cmd == "list":
            return contract.ok(sorted(registry.COMMANDS) + ["list"])
        handler = registry.resolve(cmd)
        if handler is None:
            return contract.fail("UnknownCommand", "unknown command: %s" % cmd)
        if registry.needs_app(cmd):
            import appctx

            with appctx.app_context(app_factory):
                return contract.ok(handler(params))
        return contract.ok(handler(params))
    except Exception as ex:
        sys.stderr.write("command %s failed: %r\n" % (cmd, ex))
        return contract.error_from_exception(ex)


def main(argv, stdin, stdout):
    """CLI main; returns the process exit code."""
    if len(argv) < 2:
        stdout.write(contract.dumps(contract.fail("Usage", "usage: run.py <cmd>")) + "\n")
        return 0
    cmd = argv[1]
    try:
        params = contract.parse_request(stdin.read() if cmd != "list" else "")
    except contract.HelperError as ex:
        stdout.write(contract.dumps(contract.error_from_exception(ex)) + "\n")
        return 0
    # WEKO may print on import; keep stdout reserved for the envelope.
    with contextlib.redirect_stdout(sys.stderr):
        envelope = execute(cmd, params)
    stdout.write(contract.dumps(envelope) + "\n")
    stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin, sys.stdout))
