"""bootstrap.py against a fake helper (no docker, no WEKO)."""

import json
import os
import stat
from typing import Any

import bootstrap as bs
import pytest

import weko_suite_ext

SECRET_MARK = "WEKO_TEST_TOKEN_"


def demo_facts(**overrides: Any) -> dict[str, Any]:
    """What `baseline` reports on a fresh install.sh environment."""
    users = {
        "wekosoftware@nii.ac.jp": {"active": True, "confirmed": False, "roles": [bs.ROLE_SYSTEM]},
        "repoadmin@example.org": {
            "active": True,
            "confirmed": False,
            "roles": [bs.ROLE_REPOSITORY],
        },
        "contributor@example.org": {
            "active": True,
            "confirmed": False,
            "roles": [bs.ROLE_CONTRIBUTOR],
        },
        "comadmin@example.org": {"active": True, "confirmed": False, "roles": [bs.ROLE_COMMUNITY]},
        "user@example.org": {"active": True, "confirmed": False, "roles": []},
    }
    facts: dict[str, Any] = {
        "roles": list(bs.DEMO_ROLES),
        "users": users,
        "item_types": [{"id": 30001, "name": "simple"}, {"id": 30002, "name": "full"}],
        "jsonld_mappings": [
            {"id": 30001, "name": "m1", "item_type_id": 30001},
            {"id": 30002, "name": "m2", "item_type_id": 30002},
        ],
        "flows": [{"id": 1, "name": "Registration Flow", "flow_type": 1}],
        "workflows": [
            {"id": 1, "name": "full", "itemtype_id": 30002, "flow_id": 1, "delete_flow_id": None},
            {"id": 2, "name": "simple", "itemtype_id": 30001, "flow_id": 1, "delete_flow_id": None},
        ],
        "indexes": [bs.DEMO_INDEX_ID],
        "locations": [{"name": "local", "uri": "/var/tmp", "default": True}],
        "admin_settings": [{"id": i, "name": f"s{i}"} for i in bs.DEMO_ADMIN_SETTING_IDS],
        "counts": {"sword_clients": 0, "oauth_clients": 0, "oauth_tokens": 0, "communities": 0},
        "recids": {},
        "config": {
            "WEKO_ITEMS_UI_SHARED_USER_EXCLUDED_ROLE_NAME_LIST": [bs.ROLE_SYSTEM],
            "WEKO_SWORDSERVER_SERVICEDOCUMENT_ON_BEHALF_OF": True,
        },
    }
    facts.update(overrides)
    return facts


class FakeHelper:
    """In-memory stand-in for the helper commands the bootstrap uses."""

    def __init__(self, facts: dict[str, Any] | None = None) -> None:
        self.facts = facts or demo_facts()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tokens: dict[str, dict[str, Any]] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.flows: dict[str, int] = {}
        self.workflows: dict[str, int] = {}
        self.sword: dict[str, dict[str, Any]] = {}
        self.revoked: set[str] = set()

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def __call__(self, cmd: str, params: dict[str, Any]) -> Any:
        self.calls.append((cmd, params))
        return getattr(self, "do_" + cmd)(params)

    def do_ping(self, params: dict[str, Any]) -> Any:
        return {"db_ok": True}

    def do_baseline(self, params: dict[str, Any]) -> Any:
        facts = dict(self.facts)
        facts["recids"] = {r: "R" for r in params["recids"] if r in self.records}
        return facts

    def do_create_user(self, params: dict[str, Any]) -> Any:
        self.facts["users"][params["email"]] = {
            "active": True,
            "confirmed": True,
            "roles": params["roles"],
        }
        return {"created": True}

    def do_create_flow(self, params: dict[str, Any]) -> Any:
        flow_id = self.flows.setdefault(params["flow_name"], 100 + len(self.flows))
        return {"id": flow_id}

    def do_create_workflow(self, params: dict[str, Any]) -> Any:
        assert params["delete_flow_name"] in self.flows
        return {"id": self.workflows.setdefault(params["flows_name"], 10 + len(self.workflows))}

    def do_create_token(self, params: dict[str, Any]) -> Any:
        key = params["name"]
        if key not in self.tokens:
            n = len(self.tokens)
            self.tokens[key] = {
                "access_token": f"{SECRET_MARK}{n:04d}secret",
                "client_id": f"client-{n}",
                "scopes": params["scopes"],
                "user": params["user_email"],
            }
        return dict(self.tokens[key])

    def do_register_sword_client(self, params: dict[str, Any]) -> Any:
        self.sword[params["client_id"]] = params
        return {"created": True}

    def do_revoke_token(self, params: dict[str, Any]) -> Any:
        self.revoked.add(params["access_token"])
        self.tokens = {
            k: v for k, v in self.tokens.items() if v["access_token"] != params["access_token"]
        }
        return {"deleted_tokens": [1]}

    def do_create_record(self, params: dict[str, Any]) -> Any:
        created = params["recid"] not in self.records
        self.records.setdefault(params["recid"], params)
        return {"created": created}

    def do_delete_record(self, params: dict[str, Any]) -> Any:
        self.records[params["recid"]]["deleted"] = True
        return {"deleted": True}


def run(fake: FakeHelper, **kw: Any) -> tuple[dict[str, str], list[str]]:
    lines: list[str] = []
    env = bs.bootstrap(bs.Config(), fake, lines.append, **kw)
    return env, lines


def test_baseline_of_a_fresh_install_has_no_errors_only_infos() -> None:
    report = bs.evaluate_baseline(demo_facts(), bs.Config())
    assert report.ok, report.errors
    assert report.missing_users == []
    assert any("no deletion flow" in i for i in report.infos)
    assert any("confirmed_at" in w for w in report.warnings)


def test_baseline_lists_missing_prerequisites() -> None:
    facts = demo_facts(
        roles=[bs.ROLE_SYSTEM],
        item_types=[{"id": 30001, "name": "x"}],
        jsonld_mappings=[],
        workflows=[],
        flows=[],
        locations=[],
        recids={bs.Config().recid(9): "R"},
    )
    del facts["users"]["user@example.org"]
    facts["users"]["repoadmin@example.org"]["roles"] = []
    report = bs.evaluate_baseline(facts, bs.Config())
    text = "\n".join(report.errors)
    for needle in (
        "role missing: Repository Administrator",
        "item type missing: 30002",
        "jsonld mapping missing: 30001",
        "workflow missing: id 2",
        "registration flow missing",
        "no files location",
        "R9",
        "lacks role Repository Administrator",
    ):
        assert needle in text, needle
    assert report.missing_users == ["user@example.org"]


def test_obo_users_are_checked_against_the_excluded_roles() -> None:
    cfg = bs.Config(obo_ok="wekosoftware@nii.ac.jp", obo_ng="contributor@example.org")
    report = bs.evaluate_baseline(demo_facts(), cfg)
    assert any("OBO OK user" in e for e in report.errors)
    assert any("OBO NG user" in e for e in report.errors)


def test_missing_obo_users_are_created_with_roles() -> None:
    cfg = bs.Config(obo_ok="sw-obo-ok@example.org", obo_ng="sw-obo-ng@example.org")
    fake = FakeHelper()
    env = bs.bootstrap(cfg, fake, lambda _: None)
    created = {p["email"]: p["roles"] for c, p in fake.calls if c == "create_user"}
    assert created == {
        "sw-obo-ok@example.org": [bs.ROLE_CONTRIBUTOR],
        "sw-obo-ng@example.org": [bs.ROLE_SYSTEM],
    }
    assert env["SW_USER_OBO_OK"] == "sw-obo-ok@example.org"


def test_run_orders_the_steps_and_registers_the_clients() -> None:
    fake = FakeHelper()
    env, _ = run(fake)
    names = fake.names()
    assert names.index("create_flow") < names.index("create_workflow")
    assert names.index("create_workflow") < names.index("register_sword_client")
    assert "create_user" not in names  # all demo users exist
    by_name = {
        v["client_id"]: fake.sword[v["client_id"]]
        for v in fake.tokens.values()
        if v["client_id"] in fake.sword
    }
    cw = fake.sword[env["SW_CLIENT_ID_2"]]
    assert cw["registration_type"] == "Workflow"
    assert cw["workflow_id"] == fake.workflows[bs.WORKFLOW_NAME]
    assert cw["mapping_id"] == 30001
    assert fake.sword[env["SW_CLIENT_ID_1"]]["registration_type"] == "Direct"
    assert env["SW_CLIENT_ID_X"] not in fake.sword  # C-X has no SwordClient
    assert env["SW_CLIENT_ID_X"] not in by_name
    assert env["SW_DELETE_FLOW_ID"] == str(fake.flows[bs.DELETE_FLOW_NAME])


def test_token_scopes_follow_the_spec() -> None:
    fake = FakeHelper()
    env, _ = run(fake)
    scopes = {n: v["scopes"] for n, v in fake.tokens.items()}
    assert bs.SCOPE_ACTIVITY in scopes["sw-cd-1"]
    assert bs.SCOPE_ACTIVITY not in scopes["sw-cd-2"] and "item:delete" in scopes["sw-cd-2"]
    assert scopes["sw-cd-5"] == []
    assert env["SW_TOKEN_4"] == ""
    assert env["SW_TOKEN_3"] == env["SW_TOKEN_REVOKED"]
    assert env["SW_TOKEN_REVOKED"] in fake.revoked
    assert env["SW_TOKEN_REV"] not in fake.revoked  # T-REV stays live for S1-02
    assert env["SW_TOKEN_ROLE_SYSADMIN"] == env["SW_TOKEN_1"]
    owners = {n: v["user"] for n, v in fake.tokens.items()}
    assert owners["sw-role-general"] == "user@example.org"
    assert owners["sw-role-contributor"] == "contributor@example.org"


def test_records_r1_to_r8_are_created_r3_deleted_r9_never() -> None:
    fake = FakeHelper()
    env, _ = run(fake)
    assert sorted(fake.records) == [str(900000 + n) for n in range(1, 9)]
    assert fake.records["900003"].get("deleted") is True
    assert not any(r.get("deleted") for k, r in fake.records.items() if k != "900003")
    assert (
        fake.records["900002"]["with_doi"] is True and fake.records["900001"]["with_doi"] is False
    )
    assert env["SW_R9"] == "900009" and "900009" not in fake.records
    assert all(int(env[f"SW_R{n}"]) >= 900000 for n in range(1, 10))


def test_second_run_converges_and_keeps_tokens() -> None:
    fake = FakeHelper()
    first, _ = run(fake)
    second, _ = run(fake)
    changed = {k for k in first if first[k] != second[k]}
    # The pre-revoked token is minted again on every run (its row is gone); nothing else moves.
    assert changed <= {"SW_TOKEN_3", "SW_TOKEN_REVOKED"}
    assert any("R1 (900001) exists already" in line for line in run(fake)[1])


def test_baseline_errors_block_unless_forced() -> None:
    fake = FakeHelper(demo_facts(item_types=[]))
    with pytest.raises(bs.BootstrapError):
        run(fake)
    assert "create_flow" not in fake.names()
    run(fake, force=True)
    assert "create_flow" in fake.names()


def test_dry_run_prints_calls_and_no_secrets() -> None:
    lines: list[str] = []
    env = bs.bootstrap(bs.Config(), bs.dry_run_call(lines.append), lines.append, dry_run=True)
    text = "\n".join(lines)
    assert "create_token" in text and "create_record" in text and "register_sword_client" in text
    assert "uspass123" not in text and '"password": "***"' in text
    assert "SW_TOKEN_1" in env


def test_log_never_contains_token_values() -> None:
    fake = FakeHelper()
    _, lines = run(fake)
    text = "\n".join(lines)
    assert SECRET_MARK not in text and "uspass123" not in text


def test_render_and_write_env_are_private(tmp_path) -> None:
    values = {"SW_TOKEN_1": "tok", "SW_R1": "900001", "WEKO_BASE_URL": "http://x"}
    path = tmp_path / ".env.local"
    bs.write_env(path, values)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert bs.parse_env(path.read_text()) == values
    assert bs.secret_names(values) == ["SW_TOKEN_1"]
    assert not list(tmp_path.glob("*.tmp"))


def test_env_example_declares_every_variable_the_bootstrap_writes() -> None:
    declared = set(bs.parse_env((bs.ROOT / ".env.example").read_text("utf-8")))
    env, _ = run(FakeHelper())
    assert set(env) - {k for k in env if k in bs.PASSTHROUGH} <= declared


def test_main_baseline_check_exit_codes(capsys) -> None:
    good = FakeHelper()
    assert bs.main(["baseline-check"], call=good) == 0
    bad = FakeHelper(demo_facts(roles=[]))
    assert bs.main(["baseline-check"], call=bad) == 1
    assert "role missing" in capsys.readouterr().out


def test_main_run_writes_env_file_and_prints_names_only(tmp_path, capsys) -> None:
    target = tmp_path / ".env.local"
    code = bs.main(["run", "--env-file", str(target)], call=FakeHelper(), root=tmp_path)
    out = capsys.readouterr().out
    assert code == 0 and target.is_file()
    assert SECRET_MARK not in out and "SW_TOKEN_1" in out
    assert SECRET_MARK in target.read_text()


def test_main_dry_run_writes_nothing(tmp_path) -> None:
    target = tmp_path / ".env.local"

    def forbidden(cmd: str, params: dict[str, Any]) -> Any:
        raise AssertionError("dry run must not call the helper")

    assert bs.main(["run", "--dry-run", "--env-file", str(target)], call=forbidden) == 0
    assert not target.exists()


def test_helper_failure_is_reported(capsys) -> None:
    def failing(cmd: str, params: dict[str, Any]) -> Any:
        raise bs.HelperFailure(cmd, "UserNotFound", "no such user")

    assert bs.main(["baseline-check"], call=failing) == 2
    assert "UserNotFound" in capsys.readouterr().err


def test_helper_call_speaks_the_helper_contract() -> None:
    seen = []

    def runner(argv: list[str], stdin: str, timeout: float) -> tuple[int, str, str]:
        seen.append((argv, json.loads(stdin)))
        if argv[-1] == "ping":
            return 0, json.dumps({"ok": True, "result": {"db_ok": True}}), ""
        error = {"type": "UserNotFound", "message": "nope"}
        return 0, json.dumps({"ok": False, "error": error}), ""

    previous = weko_suite_ext.set_runner(runner)
    try:
        assert bs.helper_call("ping", {}) == {"db_ok": True}
        with pytest.raises(bs.HelperFailure, match="UserNotFound"):
            bs.helper_call("create_record", {"title": "t"})
        weko_suite_ext.set_runner(lambda *_: (1, "", "docker: not found"))
        with pytest.raises(bs.HelperFailure, match="docker exec exited"):
            bs.helper_call("ping", {})
    finally:
        weko_suite_ext.set_runner(previous)
    assert seen[1][1] == {"title": "t"}


def test_c_w_has_a_second_token_without_the_activity_scope():
    specs = {s.token_env: s for s in bs.token_specs(None)}  # cfg is not read
    assert specs["SW_TOKEN_W2"].sword == "Workflow"
    assert specs["SW_TOKEN_W2"].scopes == bs.SCOPES_NO_ACTIVITY
    assert specs["SW_TOKEN_W"].scopes == bs.SCOPES_FULL
