"""plugin.yaml loads, and its SWORD operations put the right things on the wire."""

from pathlib import Path

import httpx
import pytest
from agentic_test_hub_runner import ExecutionContext, HttpExecutor, load_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = load_manifest((ROOT / "plugin.yaml").read_text())

REQUIRED_OPERATIONS = [
    "OP-SWORD-GET-SERVICE-DOC",
    "OP-SWORD-POST",
    "OP-SWORD-POST-NOFILE",
    "OP-SWORD-GET-DEPOSIT",
    "OP-SWORD-PUT",
    "OP-SWORD-DELETE",
    "OP-HELPER",
    "OP-DOCKER-LOGS",
    "OP-APP-LOG",
    "OP-REDIS-CLI",
    "OP-DOCKER-STOP",
    "OP-DOCKER-START",
    "OP-DOCKER-RESTART",
]


def _send(op_id, params, root=ROOT):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    executor = HttpExecutor(httpx.Client(transport=httpx.MockTransport(handler)))
    context = ExecutionContext(
        manifest=MANIFEST,
        scopes={"env": {"WEKO_BASE_URL": "http://weko.invalid"}, "param": params},
        root=str(root),
    )
    result = executor.run(MANIFEST.operations[op_id], context)
    assert result.ok
    return seen[-1]


@pytest.fixture
def zip_file(tmp_path):
    (tmp_path / "p.zip").write_bytes(b"PK")
    return tmp_path


def test_declares_every_required_operation():
    for op_id in REQUIRED_OPERATIONS:
        assert op_id in MANIFEST.operations, op_id


def test_helper_is_an_extension_and_the_module_is_declared():
    assert MANIFEST.extension_module == "weko_suite_ext"
    assert MANIFEST.operations["OP-HELPER"]["handler"] == "helper"


def test_no_database_or_search_connection_is_declared():
    assert set(MANIFEST.connections) == {"api", "ui"}


def test_post_sends_every_header_and_a_file_part(zip_file):
    request = _send(
        "OP-SWORD-POST",
        {
            "token": "T",
            "file": "p.zip",
            "filename": "p.zip",
            "contentDisposition": "attachment; filename=p.zip",
            "packaging": "http://purl.org/net/sword/3.0/package/SimpleZip",
            "digest": "SHA-256=abc",
            "onBehalfOf": "u@example.invalid",
            "metadataFormat": "https://w3id.org/ro/crate/1.1/",
        },
        zip_file,
    )
    assert request.method == "POST"
    assert request.url.path == "/sword/service-document"
    h = request.headers
    assert h["authorization"] == "Bearer T"
    assert h["content-disposition"] == "attachment; filename=p.zip"
    assert h["packaging"].endswith("/SimpleZip")
    assert h["digest"] == "SHA-256=abc"
    assert h["on-behalf-of"] == "u@example.invalid"
    assert h["metadata-format"].startswith("https://w3id.org")
    assert h["content-type"].startswith("multipart/form-data")
    assert b'name="file"; filename="p.zip"' in request.content


def test_optional_headers_are_omitted_when_absent(zip_file):
    request = _send("OP-SWORD-POST", {"file": "p.zip", "filename": "p.zip"}, zip_file)
    for name in ("authorization", "content-disposition", "packaging", "digest", "on-behalf-of"):
        assert name not in request.headers


def test_part_filename_can_be_empty(zip_file):
    request = _send("OP-SWORD-POST", {"file": "p.zip", "filename": ""}, zip_file)
    assert b'name="file"; filename=""' in request.content


def test_unauthenticated_variant_never_sends_authorization(zip_file):
    request = _send(
        "OP-SWORD-POST-UNAUTH", {"file": "p.zip", "filename": "p.zip", "token": "T"}, zip_file
    )
    assert "authorization" not in request.headers


def test_nofile_variant_sends_no_file_part():
    request = _send("OP-SWORD-POST-NOFILE", {"token": "T"})
    assert b'name="file"' not in request.content
    assert b'name="note"' in request.content


def test_put_and_delete_target_the_record():
    put = _send("OP-SWORD-PUT-NOFILE", {"recid": "123", "token": "T"})
    assert (put.method, put.url.path) == ("PUT", "/sword/deposit/123")
    delete = _send("OP-SWORD-DELETE", {"recid": "123"})
    assert (delete.method, delete.url.path) == ("DELETE", "/sword/deposit/123")
    assert "authorization" not in delete.headers


def test_the_app_log_is_a_presence_gate_never_a_content_gate():
    """`clean` works only with the `.*` ignore every entity carries (tools/check_log_rule.py).

    `informational` for every channel would make every verdict inconclusive: the hub needs one
    channel that decided. See docs/LOG-JUDGEMENT.md.
    """
    rules = MANIFEST.policy["rules"]
    assert rules["nominal"]["app_log"] == "clean"
    assert rules["error"]["app_log"] == "clean"
    assert MANIFEST.evidence["app_log"]["operation"] == "OP-APP-LOG"
    assert MANIFEST.evidence["app_log"]["params"] == {"since": "{{run.startedAt}}"}


def test_the_app_log_operation_reads_the_web_container_since_a_timestamp():
    op = MANIFEST.operations["OP-APP-LOG"]
    assert op["executor"] == "shell"
    assert op["run"] == [
        "docker", "logs", "--since", "{{param.since}}", "{{env.WEKO_WEB_CONTAINER}}"
    ]
    assert op["params"] == ["since"]
