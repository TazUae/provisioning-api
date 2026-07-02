"""
FitDesk scheduling RPCs — called from FitDesk via the ERP proxy.

HTTP: POST /api/method/provisioning_api.api.scheduling.<method_name>
Auth: Standard Frappe API key/secret forwarded by the control-plane proxy.
      These endpoints are NOT guest-accessible (no allow_guest=True).

Contrast with provisioning.py which uses the provisioning shared-secret token
and allow_guest=True. These endpoints run as the provisioned API user.
"""

from __future__ import annotations

import frappe


@frappe.whitelist(methods=["POST"])
def bulk_create_sessions(sessions=None):
    """
    Create multiple FD Session documents in a single atomic request.

    Frappe wraps the entire handler in a DB transaction. If any session fails
    validation the whole batch rolls back — no partial inserts.

    Accepts ``sessions`` as a JSON array (string) or a Python list (when
    Frappe has already parsed the JSON body into form_dict).

    Returns: ``{"created": [list of docnames]}``
    """
    if sessions is None:
        frappe.throw("sessions is required", frappe.ValidationError)

    if isinstance(sessions, str):
        sessions = frappe.parse_json(sessions)

    if not isinstance(sessions, list):
        frappe.throw("sessions must be an array", frappe.ValidationError)

    created = []
    for raw in sessions:
        if not isinstance(raw, dict):
            frappe.throw("Each session must be an object", frappe.ValidationError)
        doc = frappe.get_doc({"doctype": "FD Session", **raw})
        doc.insert(ignore_permissions=True)
        created.append(doc.name)

    return {"created": created}


@frappe.whitelist(methods=["POST"])
def create_series(series=None):
    """
    Create a single FD Session Series document.

    Returns: ``{"name": docname}``
    """
    if series is None:
        frappe.throw("series is required", frappe.ValidationError)

    if isinstance(series, str):
        series = frappe.parse_json(series)

    if not isinstance(series, dict):
        frappe.throw("series must be an object", frappe.ValidationError)

    doc = frappe.get_doc({"doctype": "FD Session Series", **series})
    doc.insert(ignore_permissions=True)

    return {"name": doc.name}
