import pytest

import cmd_create_token as tok
import cmd_create_user as usr
import cmd_register_sword_client as sw
import contract


def test_user_parse_and_roles():
    args = usr.parse({"email": "a@b.c", "password": "p", "roles": ["x", "y", "x"]})
    assert args["roles"] == ["x", "y"]
    assert usr.missing_roles(["x"], ["x", "y"]) == ["y"]
    with pytest.raises(contract.HelperError):
        usr.parse({"email": "nope", "password": "p"})


def test_token_empty_scopes_allowed():
    args = tok.parse({"user_email": "a@b.c", "name": "n", "scopes": []})
    assert args["scopes"] == [] and tok.scope_string([]) == ""
    assert tok.scope_string(["a", "b"]) == "a b"


def test_token_validation():
    base = {"user_email": "a@b.c", "name": "n"}
    with pytest.raises(contract.HelperError):
        tok.parse(dict(base, scopes=["bad scope"]))
    with pytest.raises(contract.HelperError):
        tok.parse(dict(base, client_name="x" * 41))
    assert tok.parse(base)["client_name"] == "n"


def test_revoke_xor():
    with pytest.raises(contract.HelperError):
        tok.parse_revoke({})
    with pytest.raises(contract.HelperError):
        tok.parse_revoke({"access_token": "a", "name": "n"})
    assert tok.parse_revoke({"name": "n"})["name"] == "n"


def test_registration_type():
    assert sw.resolve_registration_type("Direct") == 1
    assert sw.resolve_registration_type("Workflow") == 2
    assert sw.resolve_registration_type(99) == 99
    assert sw.resolve_registration_type(-1) == -1
    for bad in (True, "direct", 1.5, None):
        with pytest.raises(contract.HelperError):
            sw.resolve_registration_type(bad)


def test_coerce_field():
    assert sw.coerce_field("registration_type", "Workflow") == ("registration_type_id", 2)
    assert sw.coerce_field("registration_type_id", 7) == ("registration_type_id", 7)
    assert sw.coerce_field("workflow_id", None) == ("workflow_id", None)
    for field, value in (("mapping_id", None), ("active", 1), ("nope", 1), ("mapping_id", True)):
        with pytest.raises(contract.HelperError):
            sw.coerce_field(field, value)


def test_register_parse():
    with pytest.raises(contract.HelperError):
        sw.parse({})
    with pytest.raises(contract.HelperError):
        sw.parse({"client_id": "a", "client_name": "b"})
    args = sw.parse({"client_name": "c", "registration_type": 5, "delete_flow_id": None})
    assert args["registration_type_id"] == 5 and args["has_delete_flow_id"] is True
