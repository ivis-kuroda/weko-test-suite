"""create_record / insert_doi_pid / delete_record_row / orphan_record.

create_record mirrors ``modules/weko-swordserver/tests/helpers.py::create_record``
(recid + depid + parent pids, PIDRelations, WekoRecord, ItemsMetadata,
WekoDeposit.commit). Explicit recids should be far above the live counter
(e.g. 900000+) because the helper advances ``RecordIdentifier`` like the test
helper does.
"""

import contract

DEFAULT_DOI_PREFIX = "https://doi.org/ath-test/"


def parse(params):
    """Validate create_record arguments (pure)."""
    recid = params.get("recid")
    if recid is not None:
        if isinstance(recid, bool) or not isinstance(recid, (str, int)) or not str(recid).isdigit():
            raise contract.HelperError(
                "InvalidArgument", "recid must be a decimal string or integer"
            )
        recid = str(recid)
    return {
        "recid": recid,
        "title": contract.require_str(params, "title"),
        "owner_email": contract.require_email(params, "owner_email"),
        "with_doi": contract.optional_bool(params, "with_doi", False),
        "item_type_id": contract.optional_int(params, "item_type_id"),
    }


def build_record_data(
    recid, title, owner_id, owner_email, item_type_id, bucket_id, doi_suffix=None
):
    """Record JSON in the shape of tests/data/records/test_records.json (pure)."""
    owner = str(owner_id)
    data = {
        "_oai": {"id": "oai:weko3.example.org:%08d" % int(recid), "sets": []},
        "path": [],
        "owner": owner,
        "recid": recid,
        "title": [title],
        "pubdate": {"attribute_name": "PubDate", "attribute_value": "2022-08-20"},
        "_buckets": {"deposit": bucket_id},
        "_deposit": {
            "id": recid,
            "pid": {"type": "depid", "value": recid, "revision_id": 0},
            "owner": owner,
            "owners": [owner_id],
            "status": "published",
            "created_by": owner_id,
            "owners_ext": {"email": owner_email, "username": "", "displayname": ""},
        },
        "item_title": title,
        "author_link": [],
        "item_type_id": str(item_type_id),
        "publish_date": "2022-08-20",
        "publish_status": "0",
        "weko_shared_ids": [],
        "item_1617186331708": {
            "attribute_name": "Title",
            "attribute_value_mlt": [
                {"subitem_1551255647225": title, "subitem_1551255648112": "ja"}
            ],
        },
        "item_1617258105262": {
            "attribute_name": "Resource Type",
            "attribute_value_mlt": [
                {
                    "resourceuri": "http://purl.org/coar/resource_type/c_5794",
                    "resourcetype": "conference paper",
                }
            ],
        },
        "relation_version_is_last": True,
    }
    if doi_suffix:
        data["item_1617186819068"] = {
            "attribute_name": "Identifier Registration",
            "attribute_value_mlt": [
                {"subitem_identifier_reg_text": doi_suffix, "subitem_identifier_reg_type": "JaLC"}
            ],
        }
    return data


def build_item_data(recid, title, owner_id, owner_email, item_type_id):
    """ItemsMetadata JSON in the shape of tests/data/records/test_items.json (pure)."""
    return {
        "id": recid,
        "pid": {"type": "depid", "value": recid, "revision_id": 0},
        "lang": "ja",
        "owner": str(owner_id),
        "title": title,
        "owners": [owner_id],
        "status": "published",
        "$schema": "/items/jsonschema/%s" % item_type_id,
        "pubdate": "2022-08-20",
        "created_by": owner_id,
        "owners_ext": {"email": owner_email, "username": "", "displayname": ""},
        "shared_user_ids": [],
        "item_1617186331708": [{"subitem_1551255647225": title, "subitem_1551255648112": "ja"}],
        "item_1617258105262": {
            "resourceuri": "http://purl.org/coar/resource_type/c_5794",
            "resourcetype": "conference paper",
        },
    }


def doi_value_for(recid):
    """Default DOI URL for a recid (pure)."""
    return DEFAULT_DOI_PREFIX + str(recid)


def run(params):
    """Create the deposit/record. UNVERIFIED until run in a real container."""
    import uuid

    from invenio_accounts.models import User
    from invenio_db import db
    from invenio_pidrelations.models import PIDRelation
    from invenio_pidstore.models import PersistentIdentifier, PIDStatus, RecordIdentifier
    from weko_deposit.api import WekoDeposit, WekoRecord
    from weko_records.api import ItemsMetadata
    from weko_records.models import ItemType

    args = parse(params)
    owner = User.query.filter_by(email=args["owner_email"]).one_or_none()
    if owner is None:
        raise contract.HelperError("UserNotFound", "no such user: %s" % args["owner_email"])
    item_type_id = args["item_type_id"]
    if item_type_id is None:
        first = ItemType.query.order_by(ItemType.id).first()
        if first is None:
            raise contract.HelperError("ItemTypeNotFound", "no item type exists")
        item_type_id = first.id

    recid_value = args["recid"]
    if recid_value is not None:
        existing = PersistentIdentifier.query.filter_by(
            pid_type="recid", pid_value=recid_value
        ).first()
        if existing is not None:
            return {"recid": recid_value, "uuid": str(existing.object_uuid), "created": False}
    else:
        recid_value = str(RecordIdentifier.next())

    doi_text = "ath-test/%s" % recid_value if args["with_doi"] else None
    record_data = build_record_data(
        recid_value, args["title"], owner.id, owner.email, item_type_id, str(uuid.uuid4()), doi_text
    )
    item_data = build_item_data(recid_value, args["title"], owner.id, owner.email, item_type_id)

    rec_uuid = uuid.uuid4()
    with db.session.begin_nested():
        recid = PersistentIdentifier.create(
            "recid",
            recid_value,
            object_type="rec",
            object_uuid=rec_uuid,
            status=PIDStatus.REGISTERED,
        )
        depid = PersistentIdentifier.create(
            "depid",
            recid_value,
            object_type="rec",
            object_uuid=rec_uuid,
            status=PIDStatus.REGISTERED,
        )
        db.session.add(PIDRelation.create(recid, depid, 3))
        doi = None
        if doi_text:
            doi = PersistentIdentifier.create(
                "doi",
                "https://doi.org/" + doi_text,
                object_type="rec",
                object_uuid=rec_uuid,
                status=PIDStatus.REGISTERED,
            )
        parent = PersistentIdentifier.create(
            "parent",
            "parent:%s" % recid_value,
            object_type="rec",
            object_uuid=rec_uuid,
            status=PIDStatus.REGISTERED,
        )
        db.session.add(PIDRelation.create(parent, recid, 2, 0))
        record = WekoRecord.create(record_data, id_=rec_uuid)
        ItemsMetadata.create(item_data, id_=rec_uuid)
        WekoDeposit(record, record.model).commit()
    db.session.commit()
    return {
        "recid": recid_value,
        "uuid": str(rec_uuid),
        "created": True,
        "item_type_id": item_type_id,
        "doi": doi.pid_value if doi is not None else None,
    }


def run_insert_doi_pid(params):
    """Add a REGISTERED doi PID for a record (idempotent). UNVERIFIED."""
    from invenio_db import db
    from invenio_pidstore.models import PersistentIdentifier, PIDStatus

    recid = contract.require_str(params, "recid")
    value = contract.optional_str(params, "doi", doi_value_for(recid))
    rec = PersistentIdentifier.query.filter_by(pid_type="recid", pid_value=recid).first()
    if rec is None:
        raise contract.HelperError("RecordNotFound", "no recid pid for %s" % recid)
    existing = PersistentIdentifier.query.filter_by(pid_type="doi", pid_value=value).first()
    if existing is not None:
        return {"doi": value, "created": False, "object_uuid": str(existing.object_uuid)}
    PersistentIdentifier.create(
        "doi", value, object_type="rec", object_uuid=rec.object_uuid, status=PIDStatus.REGISTERED
    )
    db.session.commit()
    return {"doi": value, "created": True, "object_uuid": str(rec.object_uuid)}


def run_delete_record_row(params):
    """Delete metadata rows but keep the PIDs; return a restorable backup.

    Restore with ``orphan_record`` ``{"restore": <backup>}``. UNVERIFIED.
    """
    import rowlib
    from dbx import SessionDb

    if "restore" in params:
        return rowlib.restore_rows(SessionDb(), params["restore"])
    recid = contract.require_str(params, "recid")
    tables = contract.str_list(params, "tables", default=["records_metadata"])
    return rowlib.delete_rows(SessionDb(), recid, tables)


def run_orphan_record(params):
    """M15 helper: record rows gone while the recid PID remains.

    ``{"recid": ...}`` deletes records_metadata and item_metadata rows;
    ``{"restore": backup}`` puts them back. UNVERIFIED.
    """
    import rowlib
    from dbx import SessionDb

    if "restore" in params:
        return rowlib.restore_rows(SessionDb(), params["restore"])
    recid = contract.require_str(params, "recid")
    return rowlib.delete_rows(SessionDb(), recid, ["records_metadata", "item_metadata"])
