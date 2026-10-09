"""Behaviour of the SWORD mechanics rig (tools/sword-stub), over real HTTP.

The rig is not WEKO; these tests pin the check order and the error documents it
reproduces from weko_swordserver (views.py / decorators.py / errors.py).
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest
from httpx_empty import EmptyFilename
from stubutil import (
    ADMIN,
    EXAMPLE_CONFIG,
    ROOT,
    Running,
    bf,
    deposit_headers,
    errtable,
    fixture_bytes,
)


@pytest.fixture()
def rig(tmp_path):
    running = Running(copy.deepcopy(EXAMPLE_CONFIG), str(tmp_path / "app.log"))
    running.log_path = tmp_path / "app.log"
    yield running
    running.stop()


@pytest.fixture()
def client(rig):
    with httpx.Client(base_url=rig.url, timeout=10) as http:
        yield http


def auth(token: str = ADMIN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def post(
    client,
    name,
    token=ADMIN,
    data=None,
    headers=None,
    filename=None,
    part_name="file",
    path="/sword/service-document",
    method="POST",
    **kw,
):
    data = data if data is not None else fixture_bytes(name)
    h = deposit_headers(name, data, token=token, filename=filename)
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    send_name = name if filename is None else filename
    return client.request(method, path, headers=h, files={part_name: (send_name, data)}, **kw)


def assert_code(resp, code, status=None):
    type_, st, message = errtable.describe(code)
    assert resp.status_code == (status or st), resp.text
    body = resp.json()
    assert set(body) == {"@context", "@type", "timestamp", "error"}
    assert body["@type"] == type_
    assert body["error"].startswith(f"WEKO_SWORDSERVER_E_{code}: ")
    assert resp.headers["x-stub"] == "sword-mechanics-rig"
    return body


# -- the catalogue ---------------------------------------------------------


def test_status_matches_error_code_map_when_available():
    try:
        raw = subprocess.check_output(
            ["git", "show", "spec-draft/sword-error-codes:fixtures/error-code-map.json"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("spec-draft/sword-error-codes is not available here")
    entries = {e["code"]: e for e in json.loads(raw)}
    assert set(entries) == set(errtable.SPECS)
    for code, entry in entries.items():
        assert errtable.describe(code)[1] == entry["status"], code
        assert errtable.msgid(code) == entry["msgid"], code


def test_status_matches_committed_map_excerpt():
    excerpt = json.loads(
        (Path(__file__).parent / "data" / "error-code-map.json").read_text("utf-8")
    )
    entries = excerpt if isinstance(excerpt, list) else excerpt.get("codes", excerpt)
    for entry in entries:
        assert errtable.describe(entry["code"])[1] == entry["status"]


# -- authentication (no WEKO code) ------------------------------------------


def test_banner_header_everywhere(client):
    assert client.get("/sword/service-document").headers["x-stub"] == "sword-mechanics-rig"
    assert client.get("/nowhere").headers["x-stub"] == "sword-mechanics-rig"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer nope"},
        auth("STUBTOKEN-revoked"),
        {"Authorization": "Basic abc"},
    ],
)
def test_401_without_code(client, headers):
    resp = client.get("/sword/service-document", headers=headers)
    assert resp.status_code == 401
    body = resp.json()
    assert body["@type"] == "AuthenticationRequired"
    assert body["error"] == "Authentication is required."
    assert "WEKO_SWORDSERVER_E_" not in body["error"]


def test_401_before_everything_else_on_post(client):
    resp = client.post("/sword/service-document", content=b"not even multipart")
    assert resp.status_code == 401


@pytest.mark.parametrize("token", ["STUBTOKEN-no-scope", "STUBTOKEN-contributor"])
def test_403_scope_or_role_without_code(client, token):
    resp = post(client, "simplezip-normal.zip", token=token)
    assert resp.status_code == 403
    assert resp.json()["@type"] == "Forbidden"
    assert "WEKO_SWORDSERVER_E_" not in resp.json()["error"]


def test_get_needs_no_scope(client):
    assert (
        client.get("/sword/service-document", headers=auth("STUBTOKEN-no-scope")).status_code == 200
    )


# -- On-Behalf-Of -----------------------------------------------------------


def test_obo_disabled_412_1202_on_every_endpoint(client):
    h = {**auth(), "On-Behalf-Of": "someone@example.invalid"}
    for resp in (
        client.get("/sword/service-document", headers=h),
        client.get("/sword/deposit/1", headers=h),
        client.delete("/sword/deposit/6", headers=h),
        post(client, "simplezip-normal.zip", headers={"On-Behalf-Of": "someone@example.invalid"}),
    ):
        assert_code(resp, "1202")


def test_obo_precedes_file_checks(client):
    resp = client.post(
        "/sword/service-document", headers={**auth(), "On-Behalf-Of": "x"}, data={"note": "no file"}
    )
    assert_code(resp, "1202")


def test_obo_enabled_unknown_and_forbidden_users():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"].update(
        on_behalf_of=True, obo_users={"ok@example.invalid": True, "ng@example.invalid": False}
    )
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            assert (
                c.get(
                    "/sword/service-document",
                    headers={**auth(), "On-Behalf-Of": "ok@example.invalid"},
                ).status_code
                == 200
            )
            assert_code(
                post(c, "simplezip-normal.zip", headers={"On-Behalf-Of": "who@example.invalid"}),
                "1203",
            )
            assert_code(
                post(c, "simplezip-normal.zip", headers={"On-Behalf-Of": "ng@example.invalid"}),
                "1204",
            )
            ok = post(c, "simplezip-normal.zip", headers={"On-Behalf-Of": "ok@example.invalid"})
            assert ok.status_code == 201
    finally:
        running.stop()


# -- file, size, content type, packaging -----------------------------------


def test_1301_no_file_part_and_octet_stream_body(client):
    resp = client.post(
        "/sword/service-document",
        headers={**auth(), "Packaging": bf.PKG_SIMPLEZIP},
        data={"note": "x"},
    )
    assert_code(resp, "1301")
    raw = client.post(
        "/sword/service-document",
        headers={**auth(), "Content-Type": "application/zip", "Packaging": bf.PKG_SIMPLEZIP},
        content=fixture_bytes("simplezip-normal.zip"),
    )
    assert_code(raw, "1301")


def test_1302_empty_filename(client):
    data = fixture_bytes("simplezip-normal.zip")
    resp = client.post(
        "/sword/service-document",
        headers={**auth(), "Packaging": bf.PKG_SIMPLEZIP},
        files=[("file", (EmptyFilename(), data))],
    )
    assert_code(resp, "1302")


def test_1305_upload_too_large(client):
    big = bf.sized_zip(2 * 1048576)
    resp = post(client, "big.zip", data=big, headers={"Packaging": bf.PKG_SIMPLEZIP})
    body = assert_code(resp, "1305")
    assert "maxUploadSize:1048576" in body["error"]


def test_size_boundary_exact_limit_passes_size_check():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    limit = 20000
    cfg["settings"]["max_upload_size"] = limit
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            data = bf.sized_zip(limit)
            resp = post(c, "payload.zip", data=data, headers={"Packaging": bf.PKG_SIMPLEZIP})
            assert resp.request.headers["content-length"] == str(limit)
            assert resp.status_code != 413
            data = bf.sized_zip(limit + 1)
            assert_code(
                post(c, "payload.zip", data=data, headers={"Packaging": bf.PKG_SIMPLEZIP}), "1305"
            )
    finally:
        running.stop()


def test_1401_content_type(client):
    data = fixture_bytes("simplezip-normal.zip")
    resp = client.post(
        "/sword/service-document",
        headers={**auth(), "Packaging": bf.PKG_SIMPLEZIP},
        files={"file": ("simplezip-normal.zip", data, "text/plain")},
    )
    # multipart/form-data is accepted at request level, so the part's type is not consulted
    assert resp.status_code != 415
    h = deposit_headers("simplezip-normal.zip", data)
    h["Content-Type"] = "text/plain"
    resp = client.post("/sword/service-document", headers=h, content=b"x")
    assert_code(resp, "1301")


def test_1401_when_both_types_unacceptable():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["accept_archive_format"] = ["application/x-nothing"]
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            resp = post(c, "simplezip-normal.zip")
            body = assert_code(resp, "1401")
            assert "multipart/form-data" in body["error"] or "application/zip" in body["error"]
    finally:
        running.stop()


def test_1403_packaging_missing_and_1402_when_restricted(client):
    resp = post(client, "simplezip-normal.zip", headers={"Packaging": None})
    assert_code(resp, "1403")
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["accept_packaging"] = [bf.PKG_SIMPLEZIP]
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            assert_code(post(c, "bagit-normal.zip"), "1402")
            assert_code(post(c, "simplezip-normal.zip", headers={"Packaging": None}), "1402")
    finally:
        running.stop()


# -- filename ----------------------------------------------------------------


def test_1303_content_disposition_missing_or_wrong(client):
    assert_code(post(client, "simplezip-normal.zip", headers={"Content-Disposition": None}), "1303")
    assert_code(
        post(
            client,
            "simplezip-normal.zip",
            headers={"Content-Disposition": "inline; filename=x.zip"},
        ),
        "1303",
    )
    assert_code(
        post(client, "simplezip-normal.zip", headers={"Content-Disposition": "attachment"}), "1303"
    )


def test_1304_filename_differs_from_part(client):
    resp = post(
        client,
        "simplezip-normal.zip",
        headers={"Content-Disposition": "attachment; filename=other.zip"},
    )
    body = assert_code(resp, "1304")
    assert "other.zip" in body["error"]


def test_quoted_filename_accepted(client):
    resp = post(
        client,
        "simplezip-normal.zip",
        headers={"Content-Disposition": 'attachment; filename="simplezip-normal.zip"'},
    )
    assert resp.status_code == 201


# -- packaging structure ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("bagit-missing-metadata.zip", "1404"),
        ("simplezip-with-sword-json.zip", "1405"),
        ("rocrate-missing-metadata.zip", "1406"),
    ],
)
def test_packaging_structure_codes(client, name, code):
    assert_code(post(client, name), code)


def test_1407_simplezip_without_metadata_file(client):
    data = bf.build_zip({"data/readme.txt": b"nothing"})
    assert_code(
        post(client, "plain.zip", data=data, headers={"Packaging": bf.PKG_SIMPLEZIP}), "1407"
    )


def test_1408_unknown_packaging(client):
    resp = post(client, "simplezip-normal.zip", headers={"Packaging": "http://example.invalid/pkg"})
    assert_code(resp, "1408")


def test_broken_zip_is_3201_with_error_log(client, rig):
    resp = post(client, "broken.zip")
    body = assert_code(resp, "3201")
    assert body["error"].endswith("Internal Server Error")
    log = rig.log_path.read_text()
    assert " ERROR " in log and "Traceback (most recent call last):" in log


# -- digest and format --------------------------------------------------------


def test_1306_digest_missing_or_wrong(client):
    assert_code(post(client, "simplezip-normal.zip", headers={"Digest": None}), "1306")
    assert_code(post(client, "simplezip-normal.zip", headers={"Digest": "SHA-256=00"}), "1306")
    assert_code(post(client, "simplezip-normal.zip", headers={"Digest": "MD5=00"}), "1306")


def test_digest_check_can_be_disabled():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["digest_verification"] = False
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            assert post(c, "simplezip-normal.zip", headers={"Digest": None}).status_code == 201
    finally:
        running.stop()


def test_1409_format_disabled_and_1410_xml_direct():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["import_enabled"] = {"XML": False}
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            body = assert_code(post(c, "simplezip-xml.zip"), "1409")
            assert body["error"].endswith("XML metadata import is not enabled.")
    finally:
        running.stop()
    running = Running(copy.deepcopy(EXAMPLE_CONFIG))
    try:
        with httpx.Client(base_url=running.url) as c:
            assert_code(post(c, "simplezip-xml.zip"), "1410")
    finally:
        running.stop()


def test_2103_unregistered_client_and_2104_2105_workflow(client):
    assert_code(post(client, "simplezip-normal.zip", token="STUBTOKEN-no-client"), "2103")


@pytest.mark.parametrize(("workflow", "code"), [("missing", "2104"), ("not_registration", "2105")])
def test_workflow_configuration_errors(workflow, code):
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["clients"]["client-workflow"]["workflow"] = workflow
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            assert_code(
                post(c, "simplezip-normal.zip", token="STUBTOKEN-workflow-no-activity"), code
            )
    finally:
        running.stop()


def test_1201_workflow_without_activity_scope(client):
    assert_code(
        post(client, "simplezip-normal.zip", token="STUBTOKEN-workflow-no-activity"), "1201"
    )


# -- item checks ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "bagit-checksum-mismatch.zip",
        "bagit-no-bagit-txt.zip",
        "bagit-non-utf8-metadata.zip",
        "bagit-jsonld-syntax-error.zip",
    ],
)
def test_1501_on_broken_metadata(client, name):
    body = assert_code(post(client, name), "1501")
    assert body["error"].startswith("WEKO_SWORDSERVER_E_1501: Item check error: ")


def test_1501_detail_names_the_problem(client):
    assert (
        "checksum mismatch for data/data.csv"
        in post(client, "bagit-checksum-mismatch.zip").json()["error"]
    )
    detail = post(client, "bagit-jsonld-syntax-error.zip").json()["error"]
    assert re.search(r"line \d+, column \d+", detail)


def test_1501_csv_without_title(client):
    csv_bytes = bf.import_csv([{".publish_status": "public"}])
    data = bf.build_zip({"data/index.csv": csv_bytes})
    assert_code(
        post(client, "notitle.zip", data=data, headers={"Packaging": bf.PKG_SIMPLEZIP}), "1501"
    )


def test_1502_item_already_registered(client):
    data = bf.put_item_zip("1")
    assert_code(post(client, "put.zip", data=data, headers={"Packaging": bf.PKG_SIMPLEZIP}), "1502")


def test_1503_duplicate_suspected():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["clients"]["client-direct"]["duplicate_check"] = True
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            first = post(c, "simplezip-title-a.zip")
            assert first.status_code == 201
            assert_code(post(c, "simplezip-title-a.zip"), "1503")
            assert post(c, "simplezip-title-b.zip").status_code == 201
    finally:
        running.stop()


# -- success paths and mutation -------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["simplezip-normal.zip", "bagit-normal.zip", "rocrate-normal.zip", "simplezip-multi-item.zip"],
)
def test_post_success_201(client, name):
    resp = post(client, name)
    assert resp.status_code == 201, resp.text
    assert re.search(r"/sword/deposit/\d+$", resp.headers["location"]) or name.endswith(
        "multi-item.zip"
    )


def test_post_get_delete_get_404(client, rig):
    created = post(client, "simplezip-normal.zip")
    recid = re.search(r"/(\d+)$", created.headers["location"]).group(1)
    assert created.json()["@id"].endswith(f"/sword/deposit/{recid}")
    got = client.get(f"/sword/deposit/{recid}", headers=auth())
    assert got.status_code == 200 and got.json()["metadata"]["dc:title"] == "Test item A"
    time_zero = client.delete(f"/sword/deposit/{recid}", headers=auth())
    assert time_zero.status_code == 204 and time_zero.content == b""
    assert_code(client.get(f"/sword/deposit/{recid}", headers=auth()), "2101")
    assert_code(client.delete(f"/sword/deposit/{recid}", headers=auth()), "2101")
    again = post(client, "simplezip-normal.zip")
    assert again.headers["location"] != created.headers["location"]  # a recid is never reused


def test_location_header_can_be_turned_off():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["location_header"] = False
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            resp = post(c, "simplezip-normal.zip")
            assert "location" not in resp.headers and resp.json()["@id"]
    finally:
        running.stop()


def test_put_success_and_consistency_errors(client):
    ok = post(
        client,
        "put.zip",
        data=bf.put_item_zip("1", "Replaced"),
        headers={"Packaging": bf.PKG_SIMPLEZIP},
        method="PUT",
        path="/sword/deposit/1",
    )
    assert ok.status_code == 200 and ok.json()["metadata"]["dc:title"] == "Replaced"
    assert (
        client.get("/sword/deposit/1", headers=auth()).json()["metadata"]["dc:title"] == "Replaced"
    )
    mismatch = post(
        client,
        "put.zip",
        data=bf.put_item_zip("6"),
        headers={"Packaging": bf.PKG_SIMPLEZIP},
        method="PUT",
        path="/sword/deposit/1",
    )
    assert_code(mismatch, "1506")
    new = post(client, "put-item-without-id.zip", method="PUT", path="/sword/deposit/1")
    assert_code(new, "1505")
    multi = post(client, "simplezip-multi-item.zip", method="PUT", path="/sword/deposit/1")
    assert_code(multi, "1504")


def test_put_unknown_recid_2101_after_package_checks(client):
    ok_shape = post(
        client,
        "put.zip",
        data=bf.put_item_zip("1"),
        headers={"Packaging": bf.PKG_SIMPLEZIP},
        method="PUT",
        path="/sword/deposit/999",
    )
    assert_code(ok_shape, "2101")
    no_file = client.put("/sword/deposit/999", headers=auth(), data={"note": "x"})
    assert_code(no_file, "1301")  # decorators run before the function body


def test_put_locked_2201_and_lock_window():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["lock_seconds"] = 60
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            body = bf.put_item_zip("3")
            assert_code(
                post(
                    c,
                    "put.zip",
                    data=body,
                    headers={"Packaging": bf.PKG_SIMPLEZIP},
                    method="PUT",
                    path="/sword/deposit/3",
                ),
                "2201",
            )
            first = post(
                c,
                "put.zip",
                data=bf.put_item_zip("1"),
                headers={"Packaging": bf.PKG_SIMPLEZIP},
                method="PUT",
                path="/sword/deposit/1",
            )
            assert first.status_code == 200
            second = post(
                c,
                "put.zip",
                data=bf.put_item_zip("1"),
                headers={"Packaging": bf.PKG_SIMPLEZIP},
                method="PUT",
                path="/sword/deposit/1",
            )
            assert_code(second, "2201")
    finally:
        running.stop()


def test_delete_conditions(client):
    assert_code(client.delete("/sword/deposit/2", headers=auth()), "2106")
    assert_code(client.delete("/sword/deposit/3", headers=auth()), "2201")
    assert_code(client.delete("/sword/deposit/4", headers=auth()), "2203")
    assert_code(client.delete("/sword/deposit/5", headers=auth()), "2202")
    assert_code(client.delete("/sword/deposit/999", headers=auth()), "2101")
    assert_code(client.delete("/sword/deposit/6", headers=auth("STUBTOKEN-no-client")), "2103")
    assert_code(
        client.delete("/sword/deposit/6", headers=auth("STUBTOKEN-workflow-no-activity")), "1201"
    )
    assert client.delete("/sword/deposit/6", headers=auth()).status_code == 204


def test_delete_without_auth_401_and_scope_403(client):
    assert client.delete("/sword/deposit/6").status_code == 401
    assert client.delete("/sword/deposit/6", headers=auth("STUBTOKEN-no-scope")).status_code == 403


def test_get_deposit_unknown_2101(client):
    body = assert_code(client.get("/sword/deposit/12345", headers=auth()), "2101")
    assert body["error"].endswith("Item not found. (recid=12345)")


def test_service_document_shape(client):
    body = client.get("/sword/service-document", headers=auth()).json()
    assert body["@type"] == "ServiceDocument" and body["maxUploadSize"] == 1048576


def test_rate_limit_2301():
    cfg = copy.deepcopy(EXAMPLE_CONFIG)
    cfg["settings"]["rate_limit"] = 2
    running = Running(cfg)
    try:
        with httpx.Client(base_url=running.url) as c:
            assert c.get("/sword/service-document", headers=auth()).status_code == 200
            assert c.get("/sword/service-document", headers=auth()).status_code == 200
            assert_code(c.get("/sword/service-document", headers=auth()), "2301")
    finally:
        running.stop()


# -- control endpoints, faults, reset -------------------------------------------


def test_state_never_shows_token_values(client):
    text = client.get("/__stub__/state").text
    assert "STUBTOKEN" not in text
    state = json.loads(text)
    assert state["revoked"] == ["revoked"] and "1" in state["records"]


def test_fault_next_n_requests(client):
    ack = client.post(
        "/__stub__/fault",
        json={"endpoint": "GET /sword/deposit/{recid}", "code": "3108", "count": 2},
    )
    assert ack.status_code == 200
    for _ in range(2):
        body = assert_code(client.get("/sword/deposit/1", headers=auth()), "3108")
        assert "retry later" in body["error"]
    assert client.get("/sword/deposit/1", headers=auth()).status_code == 200


def test_fault_3201_on_post_is_logged_as_error_with_traceback(client, rig):
    client.post(
        "/__stub__/fault", json={"endpoint": "POST /sword/service-document", "code": "3201"}
    )
    resp = post(client, "simplezip-normal.zip")
    assert_code(resp, "3201")
    assert post(client, "simplezip-normal.zip").status_code == 201
    text = rig.log_path.read_text()
    assert re.search(r"ERROR sword-stub: \[3201\] POST /sword/service-document", text)
    assert "Traceback (most recent call last):" in text


def test_fault_rejects_unknown_code(client):
    assert client.post("/__stub__/fault", json={"code": "9999"}).status_code == 400


def test_reset_restores_world(client):
    post(client, "simplezip-normal.zip")
    client.delete("/sword/deposit/6", headers=auth())
    client.post("/__stub__/fault", json={"code": "3201", "count": 5})
    client.post("/__stub__/reset", json={})
    state = client.get("/__stub__/state").json()
    assert "6" in state["records"] and state["faults"] == [] and state["next_recid"] == 100


# -- logging -----------------------------------------------------------------------


def test_log_levels_and_no_secrets(client, rig):
    client.get("/sword/service-document", headers=auth())
    post(client, "simplezip-normal.zip", headers={"Digest": None})  # 4xx
    client.post("/__stub__/fault", json={"code": "3108"})
    client.get("/sword/deposit/1", headers=auth())  # 5xx
    text = rig.log_path.read_text()
    assert re.search(r"WARNING sword-stub: \[1306\] POST /sword/service-document", text)
    assert re.search(r"ERROR sword-stub: \[3108\] GET /sword/deposit/1", text)
    assert "STUBTOKEN" not in text and "Bearer" not in text
    lines = [line for line in text.splitlines() if line.startswith("20")]
    assert all(re.match(r"\d{4}-\d\d-\d\dT[\d:.]+Z (INFO|WARNING|ERROR) ", line) for line in lines)


def test_handler_line_has_the_shape_of_the_real_one(client, rig):
    """Detailed design 2.2 step 3: "[{code}] {method} {path}: {message}"; 4xx WARNING, 5xx ERROR."""
    client.post("/sword/service-document", headers=auth(), files={"note": (None, "x")})
    client.post("/__stub__/fault", json={"code": "3109", "endpoint": "PUT /sword/deposit/{recid}"})
    client.put("/sword/deposit/1", headers=auth(), files={"note": (None, "x")})
    text = rig.log_path.read_text()
    assert re.search(
        r"^\S+ WARNING sword-stub: \[1301\] POST /sword/service-document: No file part\.$",
        text,
        re.MULTILINE,
    )
    assert re.search(r"^\S+ ERROR sword-stub: \[1301\]", text, re.MULTILINE) is None


def test_faithful_log_and_noise_add_error_lines_but_keep_the_handler_line(tmp_path):
    config = copy.deepcopy(EXAMPLE_CONFIG)
    config.setdefault("settings", {}).update({"faithful_log": True, "noise_log": True})
    log = tmp_path / "app.log"
    running = Running(config, str(log))
    try:
        with httpx.Client(base_url=running.url, timeout=10) as http:
            http.post("/sword/service-document", headers=auth(), files={"note": (None, "x")})
    finally:
        running.stop()
    text = log.read_text()
    assert "out-of-scope noise" in text and "Traceback (most recent call last):" in text
    assert re.search(r"ERROR sword-stub: No file part\.", text)  # the pre-raise line (A-5)
    assert re.search(r"WARNING sword-stub: \[1301\] POST /sword/service-document:", text)


def test_handler_log_false_leaves_the_handler_line_out(tmp_path):
    config = copy.deepcopy(EXAMPLE_CONFIG)
    config.setdefault("settings", {}).update({"handler_log": False, "faithful_log": True})
    log = tmp_path / "app.log"
    running = Running(config, str(log))
    try:
        with httpx.Client(base_url=running.url, timeout=10) as http:
            resp = http.post("/sword/service-document", headers=auth(), files={"note": (None, "x")})
    finally:
        running.stop()
    assert resp.status_code == 400
    text = log.read_text()
    assert "[1301]" not in text
    assert "ERROR sword-stub: No file part." in text  # only the pre-raise ERROR line remains


def test_unknown_path_404_and_method_405(client):
    assert client.get("/nope").status_code == 404
    assert client.request("PATCH", "/sword/service-document").status_code == 405
