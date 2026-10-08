"""Error catalogue of weko-swordserver as the stub reproduces it.

Transcribed from `weko_swordserver/errors.py` (the `ErrorType` members and the
`ErrorSpec` declarations) and the bundled `en` message catalogue, both read on
the WEKO branch `test/sword-error-codes`. The HTTP status of every code is
cross-checked against `fixtures/error-code-map.json` by `tools/tests/test_stub.py`
whenever that file can be read (it lives on the `spec-draft/sword-error-codes`
branch), so a drift between this table and the test side shows up as a failure.

This is a copy made for a mechanics rig. It is not the source of truth.
"""

from __future__ import annotations

PREFIX = "WEKO_SWORDSERVER_E_"
JSON_LD_CONTEXT = "https://swordapp.github.io/swordv3/swordv3.jsonld"

# ErrorType name -> (@type, HTTP status)
ERROR_TYPES: dict[str, tuple[str, int]] = {
    "BadRequest": ("BadRequest", 400),
    "ContentMalformed": ("ContentMalformed", 400),
    "AuthenticationRequired": ("AuthenticationRequired", 401),
    "Forbidden": ("Forbidden", 403),
    "DigestMismatch": ("DigestMismatch", 412),
    "OnBehalfOfNotAllowed": ("OnBehalfOfNotAllowed", 412),
    "MaxUploadSizeExceeded": ("MaxUploadSizeExceeded", 413),
    "ContentTypeNotAcceptable": ("ContentTypeNotAcceptable", 415),
    "MetadataFormatNotAcceptable": ("MetadataFormatNotAcceptable", 415),
    "PackagingFormatNotAcceptable": ("PackagingFormatNotAcceptable", 415),
    "NotFound": ("NotFound", 404),
    "Conflict": ("Conflict", 409),
    "TooManyRequests": ("TooManyRequests", 429),
    "ServerError": ("ServerError", 500),
    "NotImplemented": ("NotImplemented", 501),
    "ServiceUnavailable": ("ServiceUnavailable", 503),
}

# code -> (msgid, ErrorType name, message template)
SPECS: dict[str, tuple[str, str, str]] = {
    "1201": (
        "ACTIVITY_SCOPE_INSUFFICIENT",
        "Forbidden",
        "Not allowed operation in your token scope.",
    ),
    "1202": ("ON_BEHALF_OF_NOT_ALLOWED", "OnBehalfOfNotAllowed", "Not support On-Behalf-Of."),
    "1203": ("ON_BEHALF_OF_USER_NOT_FOUND", "BadRequest", "No user found by On-Behalf-Of."),
    "1204": (
        "ON_BEHALF_OF_USER_ROLE_FORBIDDEN",
        "Forbidden",
        "On-Behalf-Of user is not allowed by role.",
    ),
    "1301": ("FILE_PART_MISSING", "ContentMalformed", "No file part."),
    "1302": ("FILE_NOT_SELECTED", "ContentMalformed", "No selected file."),
    "1303": ("FILENAME_UNRESOLVABLE", "BadRequest", "Cannot get filename by Content-Disposition."),
    "1304": ("FILE_NOT_FOUND_IN_BODY", "BadRequest", "Not found {filename} in request body."),
    "1305": (
        "UPLOAD_SIZE_EXCEEDED",
        "MaxUploadSizeExceeded",
        "Content size is too large. (request:{content_length}, maxUploadSize:{max_upload_size})",
    ),
    "1306": ("DIGEST_MISMATCH", "DigestMismatch", "Failed to verify request body and digest."),
    "1401": (
        "CONTENT_TYPE_NOT_ACCEPTABLE",
        "ContentTypeNotAcceptable",
        "Not accept Content-Type: {failed_content_type}",
    ),
    "1402": (
        "PACKAGING_NOT_ACCEPTABLE",
        "PackagingFormatNotAcceptable",
        "Not accept packaging: {packaging}",
    ),
    "1403": ("PACKAGING_REQUIRED", "PackagingFormatNotAcceptable", "Packaging is required."),
    "1404": (
        "SWORDBAGIT_METADATA_MISSING",
        "MetadataFormatNotAcceptable",
        "SWORDBagIt requires metadate/sword.json.",
    ),
    "1405": (
        "SIMPLEZIP_UNEXPECTED_SWORD_JSON",
        "MetadataFormatNotAcceptable",
        "packaging format is SimpleZip, but sword.json is found.",
    ),
    "1406": (
        "ROCRATE_METADATA_MISSING",
        "MetadataFormatNotAcceptable",
        "ro-crate-metadata.json is required in data/ directory.",
    ),
    "1407": (
        "SIMPLEZIP_METADATA_FILE_MISSING",
        "ContentMalformed",
        "SimpleZip requires ro-crate-metadata.json or other metadata file.",
    ),
    "1408": (
        "PACKAGING_FORMAT_NOT_ACCEPTABLE",
        "PackagingFormatNotAcceptable",
        "Not accept packaging format: {packaging}",
    ),
    "1409": (
        "METADATA_IMPORT_DISABLED",
        "MetadataFormatNotAcceptable",
        "{file_format} metadata import is not enabled.",
    ),
    "1410": (
        "XML_DIRECT_REGISTRATION_NOT_ALLOWED",
        "MetadataFormatNotAcceptable",
        "Direct registration is not allowed for XML metadata yet.",
    ),
    "1411": (
        "UNSUPPORTED_FILE_FORMAT",
        "MetadataFormatNotAcceptable",
        "Unsupported file format: {file_format}",
    ),
    "1501": ("ITEM_CHECK_ERROR", "ContentMalformed", "Item check error: {detail}"),
    "1502": (
        "ITEM_ALREADY_REGISTERED",
        "BadRequest",
        "This item is already registered: {item_title}.",
    ),
    "1503": (
        "ITEM_DUPLICATE_SUSPECTED",
        "BadRequest",
        "Some similar items are already registered: {list_url}.",
    ),
    "1504": (
        "MULTIPLE_ITEMS_IN_PUT",
        "ContentMalformed",
        "Multiple items found in import file. Only one item is allowed for PUT requests.",
    ),
    "1505": (
        "ITEM_NOT_REGISTERED_FOR_PUT",
        "BadRequest",
        "This item is not registered yet: {item_title}",
    ),
    "1506": (
        "ITEM_ID_MISMATCH",
        "BadRequest",
        "Item id does not match. item: {item_id}, request: {recid}",
    ),
    "2101": ("ITEM_NOT_FOUND", "NotFound", "Item not found. (recid={recid})"),
    "2102": ("RECORD_NOT_FOUND", "NotFound", "Record not found."),
    "2103": (
        "SWORD_CLIENT_NOT_CONFIGURED",
        "BadRequest",
        "No SWORD API setting found for client ID that you are using.",
    ),
    "2104": ("WORKFLOW_NOT_FOUND", "BadRequest", "Workflow not found for registration your item."),
    "2105": (
        "WORKFLOW_NOT_FOR_REGISTRATION",
        "BadRequest",
        "Workflow is not for item registration.",
    ),
    "2106": ("ITEM_HAS_DOI", "BadRequest", "Cannot delete item with DOI."),
    "2201": ("ITEM_LOCKED", "Conflict", "Item {recid} will be edited by another process."),
    "2202": (
        "ITEM_IMPORT_IN_PROGRESS",
        "Conflict",
        "Item cannot be deleted because it is in import progress.",
    ),
    "2203": ("ITEM_BEING_EDITED", "Conflict", "Item cannot be deleted because it is being edited."),
    "2301": ("RATE_LIMIT_EXCEEDED", "TooManyRequests", "Too many requests."),
    "2401": (
        "REGISTRATION_PENDING_COMPLETION",
        "BadRequest",
        "Registration of item is pending completion. Please open the following URL to continue with the remaining operations: {url}.",  # noqa: E501
    ),
    "2402": (
        "UPDATE_PENDING_COMPLETION",
        "BadRequest",
        "Update of item {recid} is pending completion. Please open the following URL to continue with the remaining operations: {url}.",  # noqa: E501
    ),
    "3101": (
        "DB_ACCESS_FAILURE",
        "ServiceUnavailable",
        "Failed to get shared ID from On-Behalf-Of.",
    ),
    "3102": (
        "INVALID_REGISTRATION_TYPE",
        "ServerError",
        "Invalid registration type: {register_type}",
    ),
    "3103": (
        "INVALID_REGISTER_FORMAT",
        "ServerError",
        "Invalid register format has been set for admin setting",
    ),
    "3104": (
        "IMPORT_FAILURE",
        "ServerError",
        "Failed to import item due to a server error. Please contact the administrator.",
    ),
    "3105": (
        "UPDATE_FAILURE",
        "ServerError",
        "Failed to update item {recid} due to a server error. Please contact the administrator.",
    ),
    "3106": (
        "DELETE_FAILURE",
        "ServerError",
        "Failed to delete item {recid} due to a server error. Please contact the administrator.",
    ),
    "3107": (
        "ACTIVITY_NOT_FOUND_AFTER_CREATE",
        "NotImplemented",
        "Activity created, but not found.",
    ),
    "3108": (
        "DATABASE_UNAVAILABLE",
        "ServiceUnavailable",
        "Failed to access the database. Please retry later or contact the administrator.",
    ),
    "3109": (
        "REDIS_UNAVAILABLE",
        "ServiceUnavailable",
        "Failed to access the cache server. Please retry later or contact the administrator.",
    ),
    "3110": (
        "SEARCH_ENGINE_UNAVAILABLE",
        "ServiceUnavailable",
        "Failed to access the search service. Please retry later or contact the administrator.",
    ),
    "3201": ("INTERNAL_SERVER_ERROR", "NotImplemented", "Internal Server Error"),
    "3202": (
        "UNEXPECTED_DURING_DELETION",
        "NotImplemented",
        "Unexpected error occurred during deletion.",
    ),
}


class _Params(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def describe(code: str, **params: object) -> tuple[str, int, str]:
    """`(@type, HTTP status, message)` of one error code."""
    _msgid, type_name, template = SPECS[code]
    type_, status = ERROR_TYPES[type_name]
    return type_, status, template.format_map(_Params(params))


def msgid(code: str) -> str:
    return SPECS[code][0]
