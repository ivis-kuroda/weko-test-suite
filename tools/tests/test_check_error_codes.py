import json
from pathlib import Path

import pytest

import check_error_codes as cec

DATA = Path(__file__).parent / "data"


def _source() -> str:
    return (DATA / "errors_excerpt.py.txt").read_text(encoding="utf-8")


def _map() -> dict[str, dict]:
    return cec.load_code_map(DATA / "error-code-map.json")


def test_parse_extracts_specs_and_statuses():
    parsed = cec.parse_errors_source(_source())
    assert parsed.http_codes["ServiceUnavailable"] == 503
    codes = {s.code: s for s in parsed.specs}
    assert sorted(codes) == ["1201", "1203", "2201", "3108"]
    assert codes["1203"].msgid == "ON_BEHALF_OF_USER_NOT_FOUND"
    assert codes["1203"].error_type == "BadRequest"
    assert codes["1203"].band == "12"
    assert codes["1203"].class_name == "AuthorizationException"


def test_clean_fixture_has_no_discrepancies():
    problems, checked = cec.compare(cec.parse_errors_source(_source()), _map())
    assert problems == []
    assert checked == 4


def test_status_msgid_and_missing_codes_are_reported():
    code_map = _map()
    code_map["1201"] = {**code_map["1201"], "status": 401}
    code_map["2201"] = {**code_map["2201"], "msgid": "ITEM_LOCKED_X"}
    del code_map["3108"]
    code_map["9999"] = {"code": "9999", "msgid": "GHOST", "status": 500}
    problems, checked = cec.compare(cec.parse_errors_source(_source()), code_map)
    assert checked == 5
    assert "1201: HTTP status mismatch (errors.py 403 via ErrorType.Forbidden, map 401)" in problems
    assert "2201: msgid mismatch (errors.py 'ITEM_LOCKED', map 'ITEM_LOCKED_X')" in problems
    assert (
        "3108: in errors.py (InternalProcessException.DATABASE_UNAVAILABLE) but not in map"
        in problems
    )
    assert "9999: in map (GHOST) but not in errors.py" in problems
    assert len(problems) == 4


def test_band_mismatch_is_reported():
    source = _source().replace('"""22xx errors."""', '"""21xx errors."""')
    problems, _ = cec.compare(cec.parse_errors_source(source), _map())
    assert problems == ["2201: band mismatch (class ConcurrencyException is documented as 21xx)"]


def test_attribute_name_must_equal_msgid():
    source = _source().replace("ITEM_LOCKED = ErrorSpec", "ITEM_LOCK = ErrorSpec")
    problems, _ = cec.compare(cec.parse_errors_source(source), _map())
    assert problems == ["2201: attribute name 'ITEM_LOCK' differs from msgid 'ITEM_LOCKED'"]


def test_unknown_error_type_is_reported():
    source = _source().replace("ErrorType.Conflict)", "ErrorType.Nope)")
    problems, _ = cec.compare(cec.parse_errors_source(source), _map())
    assert problems == ["2201: unknown ErrorType.Nope"]


def test_duplicate_code_in_source_is_reported():
    source = _source() + '\n    DUP = ErrorSpec("3108", _("DUP"), ErrorType.ServiceUnavailable)\n'
    problems, _ = cec.compare(cec.parse_errors_source(source), _map())
    assert any(p.startswith("3108: declared twice") for p in problems)


def test_po_parser_handles_continuations_and_obsolete_entries():
    catalog = cec.parse_po_catalog((DATA / "messages.po").read_text(encoding="utf-8"))
    assert catalog == {
        "ACTIVITY_SCOPE_INSUFFICIENT": "Not allowed operation in your token scope.",
        "ON_BEHALF_OF_USER_NOT_FOUND": "No user found by On-Behalf-Of.",
        "ITEM_LOCKED": "Item is locked.",
    }


def test_catalog_missing_and_empty_keys_are_reported():
    catalog = {"ACTIVITY_SCOPE_INSUFFICIENT": "x", "ITEM_LOCKED": " "}
    problems, _ = cec.compare(cec.parse_errors_source(_source()), _map(), catalog)
    assert problems == [
        "1203: msgid 'ON_BEHALF_OF_USER_NOT_FOUND' missing from en catalog",
        "2201: msgid 'ITEM_LOCKED' has an empty translation in en catalog",
        "3108: msgid 'DATABASE_UNAVAILABLE' missing from en catalog",
    ]


def test_non_literal_code_is_a_parse_error():
    source = _source().replace('ErrorSpec("2201"', "ErrorSpec(CODE")
    with pytest.raises(cec.CheckError):
        cec.parse_errors_source(source)


def test_syntax_error_is_a_parse_error():
    with pytest.raises(cec.CheckError):
        cec.parse_errors_source("class (:")


def test_cli_exit_codes(tmp_path, capsys):
    errors = tmp_path / "errors.py"
    errors.write_text(_source(), encoding="utf-8")
    map_path = DATA / "error-code-map.json"
    catalog = DATA / "messages.po"

    assert cec.main(["--errors", str(errors), "--map", str(map_path)]) == 0
    assert capsys.readouterr().out.strip() == "checked 4 codes, 0 discrepancies"

    # The catalog lacks DATABASE_UNAVAILABLE, so it must fail with exit 1.
    assert (
        cec.main(["--errors", str(errors), "--map", str(map_path), "--catalog", str(catalog)]) == 1
    )
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "checked 4 codes, 1 discrepancies"

    bad_map = tmp_path / "map.json"
    bad_map.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert cec.main(["--errors", str(errors), "--map", str(bad_map)]) == 2
    assert cec.main(["--errors", str(tmp_path / "missing.py"), "--map", str(map_path)]) == 2
    assert cec.main([]) == 2
