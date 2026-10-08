"""register_sword_client / set_client_field: SwordClientModel rows.

Note: ``delete_flow_id`` is not a column of ``sword_clients``; it lives on
``workflow_workflow``. register_sword_client therefore applies it to the
referenced WorkFlow row and returns the previous value.
"""

import contract

REGISTRATION_TYPES = {"Direct": 1, "Workflow": 2}

# field -> (kind, nullable). kind: bool | int | json
FIELDS = {
    "active": ("bool", True),
    "registration_type_id": ("int", False),
    "mapping_id": ("int", False),
    "workflow_id": ("int", True),
    "duplicate_check": ("bool", False),
    "meta_data_api": ("json", True),
}


def resolve_registration_type(value):
    """Map "Direct"/"Workflow" to ints; pass raw ints through (pure).

    Raw ints (including 0, 3, -1) are accepted on purpose for invalid-value tests.
    """
    if isinstance(value, bool):
        raise contract.HelperError("InvalidArgument", "registration_type must not be a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value in REGISTRATION_TYPES:
        return REGISTRATION_TYPES[value]
    raise contract.HelperError(
        "InvalidArgument", 'registration_type must be "Direct", "Workflow" or an integer'
    )


def coerce_field(field, value):
    """Validate and normalise a set_client_field value (pure)."""
    if field == "registration_type":
        field, value = "registration_type_id", resolve_registration_type(value)
    if field not in FIELDS:
        raise contract.HelperError(
            "InvalidArgument", "field must be one of: %s" % ", ".join(sorted(FIELDS))
        )
    kind, nullable = FIELDS[field]
    if value is None:
        if not nullable:
            raise contract.HelperError("InvalidArgument", "%s cannot be null" % field)
        return field, None
    if kind == "bool" and not isinstance(value, bool):
        raise contract.HelperError("InvalidArgument", "%s must be a boolean" % field)
    if kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
        raise contract.HelperError("InvalidArgument", "%s must be an integer" % field)
    return field, value


def parse(params):
    """Validate register_sword_client arguments (pure)."""
    client_id = contract.optional_str(params, "client_id")
    client_name = contract.optional_str(params, "client_name")
    if bool(client_id) == bool(client_name):
        raise contract.HelperError(
            "InvalidArgument", "give exactly one of client_id or client_name"
        )
    args = {
        "client_id": client_id,
        "client_name": client_name,
        "mapping_name": contract.optional_str(params, "mapping_name"),
        "mapping_id": contract.optional_int(params, "mapping_id"),
        "workflow_id": contract.optional_int(params, "workflow_id"),
        "has_delete_flow_id": "delete_flow_id" in params,
        "delete_flow_id": contract.optional_int(params, "delete_flow_id"),
        "active": contract.optional_bool(params, "active", True),
        "duplicate_check": contract.optional_bool(params, "duplicate_check", False),
        "registration_type_id": None,
    }
    if "registration_type" in params:
        args["registration_type_id"] = resolve_registration_type(params["registration_type"])
    return args


def _row(obj):
    return {
        "id": obj.id,
        "client_id": obj.client_id,
        "active": obj.active,
        "registration_type_id": obj.registration_type_id,
        "mapping_id": obj.mapping_id,
        "workflow_id": obj.workflow_id,
        "duplicate_check": obj.duplicate_check,
        "meta_data_api": obj.meta_data_api,
    }


def run(params):
    """Create or update the SwordClientModel row. UNVERIFIED."""
    from invenio_db import db
    from invenio_oauth2server.models import Client
    from weko_records.models import ItemTypeJsonldMapping
    from weko_swordserver.api import SwordClient
    from weko_swordserver.models import SwordClientModel
    from weko_workflow.models import WorkFlow

    args = parse(params)
    client_id = args["client_id"]
    if client_id is None:
        clients = Client.query.filter_by(name=args["client_name"]).all()
        if len(clients) != 1:
            raise contract.HelperError(
                "ClientNotFound" if not clients else "AmbiguousClient",
                "%d OAuth clients named %r" % (len(clients), args["client_name"]),
            )
        client_id = clients[0].client_id
    elif Client.query.filter_by(client_id=client_id).one_or_none() is None:
        raise contract.HelperError("ClientNotFound", "no OAuth client %s" % client_id)

    mapping_id = args["mapping_id"]
    if args["mapping_name"]:
        mapping = ItemTypeJsonldMapping.query.filter_by(
            name=args["mapping_name"], is_deleted=False
        ).first()
        if mapping is None:
            raise contract.HelperError("MappingNotFound", "no mapping %r" % args["mapping_name"])
        mapping_id = mapping.id

    obj = SwordClient.get_client_by_id(client_id)
    created = obj is None
    previous = None
    if created:
        if mapping_id is None:
            raise contract.HelperError("InvalidArgument", "mapping_name or mapping_id is required")
        if args["registration_type_id"] is None:
            raise contract.HelperError("InvalidArgument", "registration_type is required")
        obj = SwordClientModel(
            client_id=client_id,
            active=args["active"],
            registration_type_id=args["registration_type_id"],
            mapping_id=mapping_id,
            workflow_id=args["workflow_id"],
            duplicate_check=args["duplicate_check"],
            meta_data_api=[],
        )
        db.session.add(obj)
    else:
        previous = _row(obj)
        for key in ("active", "duplicate_check"):
            if key in params:
                setattr(obj, key, args[key])
        if args["registration_type_id"] is not None:
            obj.registration_type_id = args["registration_type_id"]
        if mapping_id is not None:
            obj.mapping_id = mapping_id
        if "workflow_id" in params:
            obj.workflow_id = args["workflow_id"]
    db.session.flush()

    previous_delete_flow = None
    if args["has_delete_flow_id"]:
        workflow = WorkFlow.query.filter_by(id=obj.workflow_id).one_or_none()
        if workflow is None:
            raise contract.HelperError(
                "WorkflowNotFound", "client has no workflow to hold delete_flow_id"
            )
        previous_delete_flow = {
            "workflow_id": workflow.id,
            "delete_flow_id": workflow.delete_flow_id,
        }
        workflow.delete_flow_id = args["delete_flow_id"]
    db.session.commit()
    return {
        "created": created,
        "current": _row(obj),
        "previous": previous,
        "previous_delete_flow": previous_delete_flow,
    }


def run_set_field(params):
    """Set one column; return the previous value. UNVERIFIED."""
    from invenio_db import db
    from weko_swordserver.api import SwordClient

    client_id = contract.require_str(params, "client_id")
    field, value = coerce_field(contract.require_str(params, "field"), params.get("value"))
    obj = SwordClient.get_client_by_id(client_id)
    if obj is None:
        raise contract.HelperError("ClientNotFound", "no sword client for %s" % client_id)
    previous = getattr(obj, field)
    setattr(obj, field, value)
    db.session.commit()
    return {"client_id": client_id, "field": field, "previous": previous, "value": value}
