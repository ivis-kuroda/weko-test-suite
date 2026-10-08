"""The fake docker/helper layer, the admin screen and the CLI of tools/sword-stub."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from stubutil import ADMIN, EXAMPLE_CONFIG, ROOT, STUB_DIR, Running, stub_server

FAKE_DOCKER = STUB_DIR / "fake_docker.py"
HELPER = ["python", "/opt/ath-helpers/run.py"]


@pytest.fixture()
def rig(tmp_path):
    running = Running(copy.deepcopy(EXAMPLE_CONFIG), str(tmp_path / "app.log"))
    yield running
    running.stop()


@pytest.fixture()
def docker_bin(tmp_path):
    """A directory with a `docker` executable that is the fake."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "docker"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_DOCKER}" "$@"\n')
    wrapper.chmod(0o755)
    return bin_dir


def docker(rig, docker_bin, *args, stdin=""):
    env = {**os.environ, "STUB_URL": rig.url, "PATH": f"{docker_bin}:{os.environ['PATH']}"}
    return subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, text=True, env=env, timeout=30
    )


def helper(rig, docker_bin, cmd, params=None):
    done = docker(
        rig, docker_bin, "exec", "-i", "weko-web-1", *HELPER, cmd, stdin=json.dumps(params or {})
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_helper_contract_and_state(rig, docker_bin):
    assert helper(rig, docker_bin, "ping")["ok"] is True
    listing = helper(rig, docker_bin, "list")
    assert listing["ok"] and "snapshot" in listing["result"]
    assert helper(rig, docker_bin, "nope") == {
        "ok": False,
        "error": {"type": "UnknownCommand", "message": "unknown command: nope"},
    }
    created = helper(rig, docker_bin, "create_record", {"title": "T", "owner_email": "a@b.c"})
    recid = created["result"]["recid"]
    assert created["result"]["created"] is True
    before = helper(rig, docker_bin, "snapshot", {"tables": ["records"]})["result"]["records"]
    assert recid in before["rows"] and before["count"] == 7
    with httpx.Client(base_url=rig.url) as http:
        http.delete(f"/sword/deposit/{recid}", headers={"Authorization": f"Bearer {ADMIN}"})
    after = helper(rig, docker_bin, "snapshot", {"tables": ["records"]})["result"]["records"]
    assert recid not in after["rows"] and after["count"] == 6


def test_helper_delete_record_is_idempotent(rig, docker_bin):
    recid = helper(rig, docker_bin, "create_record", {"title": "T", "owner_email": "a@b.c"})[
        "result"
    ]["recid"]
    first = helper(rig, docker_bin, "delete_record", {"recid": recid})["result"]
    second = helper(rig, docker_bin, "delete_record", {"recid": recid})["result"]
    assert first["previous"] == "registered" and first["deleted"] is True
    assert second["previous"] == "deleted"
    with httpx.Client(base_url=rig.url) as http:
        gone = http.get(f"/sword/deposit/{recid}", headers={"Authorization": f"Bearer {ADMIN}"})
    assert gone.status_code == 404


def test_helper_token_is_prefixed_and_usable(rig, docker_bin):
    helper(
        rig,
        docker_bin,
        "create_user",
        {"email": "u@example.invalid", "password": "x", "roles": ["System Administrator"]},
    )
    made = helper(
        rig,
        docker_bin,
        "create_token",
        {
            "user_email": "u@example.invalid",
            "name": "minted",
            "scopes": ["deposit:write", "deposit:actions", "item:create"],
            "client_name": "client-direct",
        },
    )
    token = made["result"]["access_token"]
    assert token.startswith("WEKO_TEST_TOKEN_")
    with httpx.Client(base_url=rig.url) as http:
        assert (
            http.get(
                "/sword/service-document", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 200
        )
    snap = json.dumps(helper(rig, docker_bin, "snapshot", {"tables": ["tokens"]}))
    assert token not in snap


def test_helper_faults_roundtrip(rig, docker_bin):
    assert helper(rig, docker_bin, "list_faults")["result"] == []
    injected = helper(
        rig, docker_bin, "inject_fault", {"kind": "trigger_raise", "params": {"table": "records"}}
    )
    assert injected["ok"]
    assert len(helper(rig, docker_bin, "list_faults")["result"]) == 1
    with httpx.Client(base_url=rig.url) as http:
        resp = http.delete("/sword/deposit/6", headers={"Authorization": f"Bearer {ADMIN}"})
        assert resp.status_code == 501 or resp.status_code == 500
        assert resp.json()["error"].startswith("WEKO_SWORDSERVER_E_3106")
    helper(rig, docker_bin, "restore_fault", {"kind": "all"})
    assert helper(rig, docker_bin, "list_faults")["result"] == []


def test_invalid_stdin_json_is_a_helper_failure(rig, docker_bin):
    done = docker(rig, docker_bin, "exec", "-i", "weko-web-1", *HELPER, "ping", stdin="{not json")
    assert done.returncode == 0 and json.loads(done.stdout)["ok"] is False


def test_logs_since(rig, docker_bin):
    with httpx.Client(base_url=rig.url) as http:
        http.get("/sword/deposit/12345", headers={"Authorization": f"Bearer {ADMIN}"})
        marker = stub_server.iso(datetime.now(UTC) + timedelta(milliseconds=5))
        time.sleep(1.1)
        http.get("/sword/deposit/54321", headers={"Authorization": f"Bearer {ADMIN}"})
    everything = docker(rig, docker_bin, "logs", "--since", "2000-01-01T00:00:00Z", "weko-web-1")
    assert everything.stdout == "" and "12345" in everything.stderr and "54321" in everything.stderr
    recent = docker(rig, docker_bin, "logs", "--since", marker, "weko-web-1")
    assert "12345" not in recent.stderr and "54321" in recent.stderr
    assert "WARNING" in recent.stderr and "STUBTOKEN" not in recent.stderr


def test_stop_start_web_refuses_then_recovers(rig, docker_bin):
    assert docker(rig, docker_bin, "stop", "weko-web-1").returncode == 0
    with httpx.Client(base_url=rig.url) as http:
        with pytest.raises(httpx.HTTPError):
            http.get("/sword/service-document", headers={"Authorization": f"Bearer {ADMIN}"})
        assert http.get("/__stub__/state").json()["stopped"] == ["web"]
    docker(rig, docker_bin, "start", "weko-web-1")
    with httpx.Client(base_url=rig.url) as http:
        assert (
            http.get(
                "/sword/service-document", headers={"Authorization": f"Bearer {ADMIN}"}
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    ("container", "code", "method", "path"),
    [
        ("weko-db-1", "3108", "GET", "/sword/service-document"),
        ("weko-redis-1", "3109", "DELETE", "/sword/deposit/6"),
        ("weko-es-1", "3110", "GET", "/sword/deposit/1"),
    ],
)
def test_stopping_a_dependency_gives_503(rig, docker_bin, container, code, method, path):
    docker(rig, docker_bin, "stop", container)
    with httpx.Client(base_url=rig.url) as http:
        resp = http.request(method, path, headers={"Authorization": f"Bearer {ADMIN}"})
        assert resp.status_code == 503
        assert resp.json()["error"].startswith(f"WEKO_SWORDSERVER_E_{code}")
    docker(rig, docker_bin, "restart", container)
    with httpx.Client(base_url=rig.url) as http:
        assert (
            http.request(method, path, headers={"Authorization": f"Bearer {ADMIN}"}).status_code
            < 500
        )


def test_db_stopped_beats_a_valid_token(rig, docker_bin):
    docker(rig, docker_bin, "stop", "weko-db-1")
    with httpx.Client(base_url=rig.url) as http:
        assert (
            http.get(
                "/sword/service-document", headers={"Authorization": "Bearer garbage"}
            ).status_code
            == 503
        )


def test_unknown_container_and_command(rig, docker_bin):
    done = docker(rig, docker_bin, "stop", "no-such")
    assert done.returncode == 1 and "No such container" in done.stderr
    assert docker(rig, docker_bin, "ps").returncode == 1


def test_redis_cli_and_lock_simulation(rig, docker_bin):
    redis = ["exec", "-i", "weko-redis-1", "redis-cli", "-n", "1"]
    assert docker(rig, docker_bin, *redis, "SETEX", "lock_item_1", "30", "x").stdout.strip() == "OK"
    assert docker(rig, docker_bin, *redis, "EXISTS", "lock_item_1").stdout.strip() == "1"
    assert int(docker(rig, docker_bin, *redis, "TTL", "lock_item_1").stdout) > 0
    with httpx.Client(base_url=rig.url) as http:
        body = http.get("/__stub__/state").json()
        assert body["records"]["1"]["locked"] is False
    assert docker(rig, docker_bin, *redis, "DEL", "lock_item_1").stdout.strip() == "1"
    assert docker(rig, docker_bin, *redis, "GET", "missing").stdout.strip() == ""


def test_weko_suite_ext_helper_through_the_fake_docker(rig, docker_bin, monkeypatch):
    """The host-side extension shells out to `docker`; the fake plugs in via PATH."""
    sys.path.insert(0, str(ROOT))
    import weko_suite_ext

    monkeypatch.setenv("STUB_URL", rig.url)
    monkeypatch.setenv("PATH", f"{docker_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("WEKO_WEB_CONTAINER", "weko-web-1")
    result = weko_suite_ext.helper({"cmd": "ping"})
    assert result.ok and result.body["ok"] is True
    snap = weko_suite_ext.helper({"cmd": "snapshot", "params": "{}"})
    assert snap.ok and snap.body["result"]["records"]["count"] == 6


# -- admin screen ---------------------------------------------------------------


def test_admin_login_and_revoke(rig):
    with httpx.Client(base_url=rig.url) as http:
        page = http.get("/stub-admin/")
        assert 'data-testid="login-form"' in page.text and "NOT WEKO" in page.text
        bad = http.post("/stub-admin/login", data={"user": "admin", "password": "wrong"})
        assert bad.status_code == 401 and 'data-testid="login-error"' in bad.text
        ok = http.post("/stub-admin/login", data={"user": "admin", "password": "stub-admin-pass"})
        assert ok.status_code == 303
        http.cookies.set("stub_session", ok.cookies["stub_session"])
        dash = http.get("/stub-admin/")
        assert 'data-testid="revoke-direct-admin"' in dash.text and "STUBTOKEN" not in dash.text
        assert "console.error" in dash.text
        assert (
            http.get(
                "/sword/service-document", headers={"Authorization": f"Bearer {ADMIN}"}
            ).status_code
            == 200
        )
        done = http.post("/stub-admin/revoke", json={"name": "direct-admin"})
        assert done.json() == {"revoked": True, "name": "direct-admin"}
        assert (
            http.get(
                "/sword/service-document", headers={"Authorization": f"Bearer {ADMIN}"}
            ).status_code
            == 401
        )


def test_admin_revoke_needs_login(rig):
    with httpx.Client(base_url=rig.url) as http:
        assert http.post("/stub-admin/revoke", json={"name": "direct-admin"}).status_code == 401


# -- CLI ---------------------------------------------------------------------------


def test_cli_banner_and_ephemeral_port(tmp_path):
    cfg = tmp_path / "stub.json"
    cfg.write_text(json.dumps(EXAMPLE_CONFIG))
    port_file = tmp_path / "port"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(STUB_DIR / "stub_server.py"),
            "--config",
            str(cfg),
            "--port",
            "0",
            "--port-file",
            str(port_file),
            "--log-file",
            str(tmp_path / "app.log"),
        ],
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if port_file.exists() and port_file.read_text():
                break
            time.sleep(0.05)
        port = int(port_file.read_text())
        resp = httpx.get(
            f"http://127.0.0.1:{port}/sword/service-document",
            headers={"Authorization": f"Bearer {ADMIN}"},
        )
        assert resp.status_code == 200 and resp.headers["x-stub"] == "sword-mechanics-rig"
    finally:
        proc.terminate()
        _out, err = proc.communicate(timeout=10)
    assert re.search(r"MECHANICS RIG ONLY.*NOT WEKO", err)
