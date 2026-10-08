import json

import pytest
from agentic_test_hub_runner import ExecutionContext, Manifest

import weko_suite_ext

MANIFEST = Manifest(
    name="weko",
    connections={},
    operations={},
    states={},
    evidence={},
    policy=None,
    extension_module="weko_suite_ext",
)


def _ctx(env=None):
    return ExecutionContext(manifest=MANIFEST, scopes={"env": env or {}}, root=".")


@pytest.fixture
def calls():
    recorded = []
    answers = {"value": (0, json.dumps({"ok": True, "result": {"n": 1}}), "")}

    def runner(argv, stdin, timeout):
        recorded.append((argv, stdin, timeout))
        return answers["value"]

    previous = weko_suite_ext.set_runner(runner)
    yield recorded, answers
    weko_suite_ext.set_runner(previous)


def test_runs_the_helper_in_the_default_container_with_json_on_stdin(calls, monkeypatch):
    monkeypatch.delenv("WEKO_WEB_CONTAINER", raising=False)
    recorded, _ = calls
    result = weko_suite_ext.helper({"cmd": "snapshot", "params": '{"a": 1}'}, _ctx())
    argv, stdin, _ = recorded[0]
    assert argv == [
        "docker",
        "exec",
        "-i",
        "weko-web-1",
        "python",
        "/opt/ath-helpers/run.py",
        "snapshot",
    ]
    assert json.loads(stdin) == {"a": 1}
    assert result.ok is True
    assert result.body == {"ok": True, "result": {"n": 1}}
    assert json.loads(result.stdout)["ok"] is True


def test_container_comes_from_the_scoped_env(calls):
    recorded, _ = calls
    weko_suite_ext.helper({"cmd": "ping"}, _ctx({"WEKO_WEB_CONTAINER": "other-web"}))
    assert recorded[0][0][3] == "other-web"
    assert recorded[0][1] == "{}"


def test_container_comes_from_the_process_env(calls, monkeypatch):
    recorded, _ = calls
    monkeypatch.setenv("WEKO_WEB_CONTAINER", "from-os")
    weko_suite_ext.helper({"cmd": "ping"}, None)
    assert recorded[0][0][3] == "from-os"


def test_a_helper_level_failure_is_data_not_an_operation_failure(calls):
    _, answers = calls
    answers["value"] = (0, json.dumps({"ok": False, "error": {"type": "X", "message": "m"}}), "")
    result = weko_suite_ext.helper({"cmd": "create_user"}, _ctx())
    assert result.ok is True
    assert result.body["error"]["type"] == "X"


def test_non_zero_exit_fails_the_operation(calls):
    _, answers = calls
    answers["value"] = (1, "", "No such container: weko-web-1\n")
    result = weko_suite_ext.helper({"cmd": "ping"}, _ctx())
    assert result.ok is False
    assert "No such container" in result.failure
    assert result.exit_code == 1


def test_non_json_output_fails_the_operation(calls):
    _, answers = calls
    answers["value"] = (0, "Traceback...", "")
    result = weko_suite_ext.helper({"cmd": "ping"}, _ctx())
    assert result.ok is False
    assert "JSON" in result.failure


def test_missing_docker_binary_fails_the_operation():
    def runner(argv, stdin, timeout):
        raise FileNotFoundError("docker")

    previous = weko_suite_ext.set_runner(runner)
    try:
        result = weko_suite_ext.helper({"cmd": "ping"}, _ctx())
    finally:
        weko_suite_ext.set_runner(previous)
    assert result.ok is False
    assert "could not run docker" in result.failure


@pytest.mark.parametrize("cmd", [None, "", "Bad Cmd", "a;b", "../x", "-flag"])
def test_rejects_an_invalid_command_name_without_running_anything(calls, cmd):
    recorded, _ = calls
    result = weko_suite_ext.helper({"cmd": cmd}, _ctx())
    assert result.ok is False
    assert recorded == []


def test_rejects_params_that_are_not_json(calls):
    recorded, _ = calls
    result = weko_suite_ext.helper({"cmd": "ping", "params": "{nope"}, _ctx())
    assert result.ok is False
    assert recorded == []


def test_structured_params_are_serialised(calls):
    recorded, _ = calls
    weko_suite_ext.helper({"cmd": "ping", "params": {"b": 2}}, _ctx())
    assert json.loads(recorded[0][1]) == {"b": 2}
