import io
import json

import contract
import run


def call(argv, stdin=""):
    out = io.StringIO()
    code = run.main(["run.py"] + argv, io.StringIO(stdin), out)
    lines = out.getvalue().splitlines()
    assert code == 0
    assert len(lines) == 1
    return json.loads(lines[0])


def test_list_prints_names():
    env = call(["list"])
    assert env["ok"] is True
    assert "ping" in env["result"] and "inject_fault" in env["result"]


def test_unknown_command_is_ok_false():
    env = call(["nope"], "{}")
    assert env == {
        "ok": False,
        "error": {"type": "UnknownCommand", "message": "unknown command: nope"},
    }


def test_invalid_json_and_non_object():
    assert call(["ping"], "{")["error"]["type"] == "InvalidJson"
    assert call(["ping"], "[1]")["error"]["type"] == "InvalidArgument"


def test_missing_command():
    out = io.StringIO()
    assert run.main(["run.py"], io.StringIO(""), out) == 0
    assert json.loads(out.getvalue())["ok"] is False


def test_empty_stdin_is_empty_object():
    assert contract.parse_request("  ") == {}


def test_error_from_exception_keeps_sqlstate():
    class Orig(Exception):
        pgcode = "23514"

    class Wrapped(Exception):
        orig = Orig()

    env = contract.error_from_exception(Wrapped("boom"))
    assert env["error"] == {"type": "Wrapped", "message": "boom", "sqlstate": "23514"}


def test_execute_wraps_handler_errors(monkeypatch):
    import registry

    def boom(params):
        raise contract.HelperError("Custom", "bad", detail=1)

    monkeypatch.setattr(registry, "resolve", lambda name: boom)
    monkeypatch.setitem(registry.COMMANDS, "boom", ("x", "y", False))
    env = run.execute("boom", {})
    assert env == {"ok": False, "error": {"type": "Custom", "message": "bad", "detail": 1}}


def test_execute_uses_injected_app_factory(monkeypatch):
    import contextlib

    import appctx
    import registry

    class App(object):
        entered = 0

        @contextlib.contextmanager
        def app_context(self):
            App.entered += 1
            yield

    monkeypatch.setattr(registry, "resolve", lambda name: lambda p: {"echo": p})
    env = run.execute("ping", {"a": 1}, app_factory=App)
    assert env == {"ok": True, "result": {"echo": {"a": 1}}}
    assert App.entered == 1
    assert appctx  # imported lazily by run.execute


def test_validators():
    import pytest

    with pytest.raises(contract.HelperError):
        contract.require_str({}, "x")
    with pytest.raises(contract.HelperError):
        contract.optional_int({"x": True}, "x")
    assert contract.str_list({"x": ["a", "a", "b"]}, "x") == ["a", "b"]
    assert contract.str_list({}, "x", default=[]) == []
    assert contract.quote_literal("it's") == "'it''s'"
