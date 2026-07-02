"""FitDesk schema provisioning — idempotent setup of FitDesk-specific records.

Invoked by bench-agent via:
    bench --site <site> execute
        provisioning_api.api.fitdesk_setup.setup_fitdesk_schema
        --kwargs '{"company_name": "...", "company_abbr": "..."}'

Stdout contract (parsed by axis_bench_agent.bench._parse_fitdesk_result):
    ok=true
    custom_fields=<int>

All sub-functions are fully idempotent — calling them multiple times on an
already-configured site is a no-op that returns quickly.
"""

from __future__ import annotations

import os


def setup_fitdesk_schema(
    company_name: str,
    company_abbr: str = "",
    control_plane_webhook_url: str = "",
    control_plane_webhook_secret: str = "",
) -> dict:
    """Orchestrate all FitDesk-specific provisioning steps.

    Calls each sub-function in order, collecting results.  A failure in one
    sub-function is caught and recorded but does NOT stop the others — every
    step is attempted independently.

    Args:
        company_name:               Full legal company name (e.g. "Elite Training LLC").
        company_abbr:               Short abbreviation used in account naming (e.g. "ET").
        control_plane_webhook_url:  Full URL for the invoice-submitted webhook on the
                                    control plane (baked into the Server Script).
        control_plane_webhook_secret: Per-tenant HMAC secret sent as X-Webhook-Secret.

    Returns:
        {
            "ok": True,
            "custom_fields": <int>,
            "results": {
                "custom_fields": {...},
                "training_item": {...},
                "customer_group": {...},
                "territory": {...},
                "print_format": {...},
                "mode_of_payment": {...},
                "server_script": {...},
            },
            "errors": [<str>, ...]   # empty on full success
        }

    Stdout (for bench-agent parser):
        ok=true
        custom_fields=<int>
    """
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")
    company_name = company_name.strip()
    company_abbr = (company_abbr or "").strip()
    control_plane_webhook_url = (control_plane_webhook_url or "").strip()
    control_plane_webhook_secret = (control_plane_webhook_secret or "").strip()

    import frappe  # lazy — only available under bench execute / Frappe runtime

    results: dict = {}
    errors: list[str] = []

    # ── 1. Custom Fields ──────────────────────────────────────────────────────
    try:
        results["custom_fields"] = _create_custom_fields(frappe)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"custom_fields: {exc}")
        results["custom_fields"] = {"error": str(exc)}

    # ── 2. Training Item ──────────────────────────────────────────────────────
    try:
        results["training_item"] = _create_training_item(frappe, company_name, company_abbr)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"training_item: {exc}")
        results["training_item"] = {"error": str(exc)}

    # ── 3. Customer Group ─────────────────────────────────────────────────────
    try:
        results["customer_group"] = _create_customer_group(frappe)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"customer_group: {exc}")
        results["customer_group"] = {"error": str(exc)}

    # ── 4. Territory ─────────────────────────────────────────────────────────
    try:
        results["territory"] = _create_territory(frappe)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"territory: {exc}")
        results["territory"] = {"error": str(exc)}

    # ── 5. Print Format ───────────────────────────────────────────────────────
    try:
        results["print_format"] = _create_print_format(frappe)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"print_format: {exc}")
        results["print_format"] = {"error": str(exc)}

    # ── 6. Mode of Payment ────────────────────────────────────────────────────
    try:
        results["mode_of_payment"] = _create_mode_of_payment(frappe, company_name, company_abbr)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mode_of_payment: {exc}")
        results["mode_of_payment"] = {"error": str(exc)}

    # ── 7. WhatsApp Server Script ─────────────────────────────────────────────
    if control_plane_webhook_url and control_plane_webhook_secret:
        try:
            results["server_script"] = _create_whatsapp_server_script(
                frappe,
                control_plane_webhook_url,
                control_plane_webhook_secret,
                tenant_slug=getattr(frappe, "local", None) and getattr(frappe.local, "site", "") or "",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"server_script: {exc}")
            results["server_script"] = {"error": str(exc)}
    else:
        import sys
        print(
            "fitdesk_info: skipping server_script (no control_plane_webhook_url provided)",
            file=sys.stderr,
        )
        results["server_script"] = {"skipped": True, "reason": "no webhook url"}

    # ── 8. Price Lists (Standard Selling / Buying) ────────────────────────────
    try:
        results["price_lists"] = _create_price_lists(frappe)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"price_lists: {exc}")
        results["price_lists"] = {"error": str(exc)}

    # ── 9. Enable Server Scripts ──────────────────────────────────────────────
    try:
        results["server_scripts_enabled"] = _enable_server_scripts(frappe)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"server_scripts_enabled: {exc}")
        results["server_scripts_enabled"] = {"error": str(exc)}

    # ── Count successfully created / verified custom fields ───────────────────
    cf_result = results.get("custom_fields", {})
    custom_fields_count = cf_result.get("created", 0) + cf_result.get("skipped", 0)

    # Stdout contract for bench-agent
    print("ok=true")
    print(f"custom_fields={custom_fields_count}")
    if errors:
        import sys
        for err in errors:
            print(f"fitdesk_warning: {err}", file=sys.stderr)

    return {
        "ok": True,
        "custom_fields": custom_fields_count,
        "results": results,
        "errors": errors,
    }


# ── Sub-function 1: Custom Fields ─────────────────────────────────────────────

#: Custom field definitions — (target_doctype, fieldname, label, fieldtype, options, insert_after)
_CUSTOM_FIELDS = [
    # On Customer
    ("Customer", "custom_fitness_goals",       "Fitness Goals",       "Long Text", None,                                "customer_name"),
    ("Customer", "custom_trainer_notes",       "Trainer Notes",       "Long Text", None,                                "custom_fitness_goals"),
    ("Customer", "custom_package_type",        "Package Type",        "Select",    "Per Session\nMonthly\nPackage",     "custom_trainer_notes"),
    ("Customer", "custom_remaining_sessions",  "Remaining Sessions",  "Int",       None,                                "custom_package_type"),
    # On Sales Invoice
    ("Sales Invoice", "custom_session_date",       "Session Date",       "Date",  None,                                "posting_date"),
    ("Sales Invoice", "custom_session_time",       "Session Time",       "Time",  None,                                "custom_session_date"),
    ("Sales Invoice", "custom_no_show",            "No Show",            "Check", None,                                "custom_session_time"),
    ("Sales Invoice", "custom_whatsapp_sent",      "WhatsApp Sent",      "Check", None,                                "custom_no_show"),
    ("Sales Invoice", "custom_payment_link",       "Payment Link",       "Data",  None,                                "custom_whatsapp_sent"),
    ("Sales Invoice", "custom_payment_reference",  "Whish Reference",   "Data",   None,                                "custom_payment_link"),
    # Phase B additions
    ("Customer",      "custom_billing_mode",         "Billing Mode",         "Select",   "Package\nPay Per Session", "custom_remaining_sessions"),
    ("Customer",      "custom_default_session_rate",  "Default Session Rate", "Currency", None,                             "custom_billing_mode"),
    ("Customer",      "custom_package_name",          "Package Name",         "Data",     None,                             "custom_default_session_rate"),
    ("Sales Invoice", "custom_fd_session",            "FD Session",           "Data",     None,                             "custom_payment_reference"),
    ("Sales Invoice", "custom_invoice_kind",          "Invoice Kind",         "Select",   "Package\nSession",               "custom_fd_session"),
]


def _create_custom_fields(frappe) -> dict:
    """Create the 15 FitDesk Custom Field records if they don't already exist.

    Idempotent: each field is only inserted if it is absent.
    Calls frappe.clear_cache() once after all inserts.

    Returns:
        {"created": <int>, "skipped": <int>}
    """
    created = 0
    skipped = 0

    for doctype, fieldname, label, fieldtype, options, insert_after in _CUSTOM_FIELDS:
        if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}):
            skipped += 1
            continue

        cf = frappe.get_doc({
            "doctype": "Custom Field",
            "dt": doctype,
            "fieldname": fieldname,
            "label": label,
            "fieldtype": fieldtype,
            "insert_after": insert_after,
            **({"options": options} if options is not None else {}),
        })
        cf.insert(ignore_permissions=True)
        created += 1

    if created > 0:
        frappe.clear_cache()

    return {"created": created, "skipped": skipped}


# ── Sub-function 2: Training Item ─────────────────────────────────────────────

def _create_training_item(frappe, company_name: str, company_abbr: str) -> dict:
    """Create the TRAINING-SESSION item if it doesn't exist.

    Ensures the 'Services' Item Group exists (creating root + leaf if needed),
    finds income/expense accounts, then inserts the item.

    Returns:
        {"skipped": True}  — if item already existed
        {"item_code": "TRAINING-SESSION", "income_account": ..., "expense_account": ...}
    """
    if frappe.db.exists("Item", "TRAINING-SESSION"):
        return {"skipped": True}

    # ── Ensure Item Group tree exists ─────────────────────────────────────────
    if not frappe.db.exists("Item Group", "All Item Groups"):
        root = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "All Item Groups",
            "is_group": 1,
        })
        root.insert(ignore_permissions=True)
        frappe.db.commit()

    if not frappe.db.exists("Item Group", "Services"):
        svc = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "Services",
            "parent_item_group": "All Item Groups",
            "is_group": 0,
        })
        svc.insert(ignore_permissions=True)
        frappe.db.commit()

    item_group = "Services"

    # ── Ensure Nos UOM exists (normally created by setup wizard) ─────────────
    if not frappe.db.exists("UOM", "Nos"):
        uom = frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"})
        uom.insert(ignore_permissions=True)
        frappe.db.commit()

    # ── Find income account ────────────────────────────────────────────────────
    income_account = frappe.db.get_value(
        "Account",
        {"company": company_name, "account_type": "Income Account", "is_group": 0},
        "name",
    )
    if not income_account:
        income_account = frappe.db.get_value(
            "Account",
            {"company": company_name, "root_type": "Income", "is_group": 0},
            "name",
        )

    # ── Find expense account ──────────────────────────────────────────────────
    expense_account = frappe.db.get_value(
        "Account",
        {"company": company_name, "account_type": "Expense Account", "is_group": 0},
        "name",
    )
    if not expense_account:
        expense_account = frappe.db.get_value(
            "Account",
            {"company": company_name, "root_type": "Expense", "is_group": 0},
            "name",
        )

    item_defaults: list[dict] = []
    if company_name:
        defaults: dict = {"company": company_name}
        if income_account:
            defaults["income_account"] = income_account
        if expense_account:
            defaults["expense_account"] = expense_account
        item_defaults.append(defaults)

    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": "TRAINING-SESSION",
        "item_name": "Personal Training Session",
        "item_group": item_group,
        "stock_uom": "Nos",
        "is_stock_item": 0,
        "include_item_in_manufacturing": 0,
        "description": "One personal training session",
        **({"item_defaults": item_defaults} if item_defaults else {}),
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "item_code": "TRAINING-SESSION",
        "income_account": income_account,
        "expense_account": expense_account,
    }


# ── Sub-function 3: Customer Group ────────────────────────────────────────────

def _create_customer_group(frappe) -> dict:
    """Create the 'Individual' Customer Group under 'All Customer Groups'.

    Idempotent: returns {"skipped": True} if the group already exists.

    Returns:
        {"skipped": True}  or  {"customer_group": "Individual"}
    """
    if frappe.db.exists("Customer Group", "Individual"):
        return {"skipped": True}

    # Ensure the root group exists (ERPNext ships with it, but be safe)
    if not frappe.db.exists("Customer Group", "All Customer Groups"):
        root = frappe.get_doc({
            "doctype": "Customer Group",
            "customer_group_name": "All Customer Groups",
            "is_group": 1,
        })
        root.insert(ignore_permissions=True)
        frappe.db.commit()

    cg = frappe.get_doc({
        "doctype": "Customer Group",
        "customer_group_name": "Individual",
        "parent_customer_group": "All Customer Groups",
        "is_group": 0,
    })
    cg.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"customer_group": "Individual"}


# ── Sub-function 4: Territory ─────────────────────────────────────────────────

def _create_territory(frappe) -> dict:
    """Ensure the 'All Territories' root territory exists.

    ERPNext creates this during site setup.  This function is a safety net for
    edge cases where it was not created (e.g. aborted setup wizard).

    Returns:
        {"skipped": True}  or  {"territory": "All Territories"}
    """
    if frappe.db.exists("Territory", "All Territories"):
        return {"skipped": True}

    territory = frappe.get_doc({
        "doctype": "Territory",
        "territory_name": "All Territories",
        "is_group": 1,
        # parent_territory left blank → root node
    })
    territory.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"territory": "All Territories"}


# ── Sub-function 5: Print Format ──────────────────────────────────────────────

def _create_print_format(frappe) -> dict:
    """Create the FitDesk Invoice Print Format from the bundled HTML template.

    The template HTML is read from:
        provisioning_api/templates/fitdesk_invoice.html

    Idempotent: returns {"skipped": True} if the Print Format already exists.

    Returns:
        {"skipped": True}  or  {"print_format": "FitDesk Invoice"}
    """
    if frappe.db.exists("Print Format", "FitDesk Invoice"):
        return {"skipped": True}

    template_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),  # provisioning_api/
        "templates",
        "fitdesk_invoice.html",
    )
    try:
        with open(template_path, encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        raise RuntimeError(
            f"Print format template not found at {template_path!r}. "
            "Ensure fitdesk_invoice.html is bundled with the provisioning_api app."
        )

    pf = frappe.get_doc({
        "doctype": "Print Format",
        "name": "FitDesk Invoice",
        "doc_type": "Sales Invoice",
        "standard": "No",
        "custom_format": 1,
        "html": html_content,
        "print_format_type": "Jinja",
    })
    pf.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"print_format": "FitDesk Invoice"}


# ── Sub-function 6: Mode of Payment ──────────────────────────────────────────

def _get_account_for_company(
    frappe,
    company_name: str,
    preferred_account_type: str,
    fallback_account_type: str | None = None,
) -> str | None:
    """Find an account of the preferred type for the company.

    Searches for an account matching the preferred_account_type. If not found,
    optionally searches for fallback_account_type. Returns the first matching
    account name or None.

    Args:
        frappe: Frappe context
        company_name: Target company name
        preferred_account_type: Primary account_type to search (e.g. "Cash", "Bank")
        fallback_account_type: Secondary account_type to search if primary not found

    Returns:
        Account name (str) or None if no matching account found
    """
    account = frappe.db.get_value(
        "Account",
        {"company": company_name, "account_type": preferred_account_type, "is_group": 0},
        "name",
    )
    if account:
        return account

    if fallback_account_type:
        account = frappe.db.get_value(
            "Account",
            {"company": company_name, "account_type": fallback_account_type, "is_group": 0},
            "name",
        )
        if account:
            return account

    return None


def _upsert_mode_of_payment(
    frappe,
    mode_name: str,
    payment_type: str,
    company_name: str,
    account_name: str,
) -> dict:
    """Create or update a Mode of Payment with company account mapping.

    Fully idempotent:
    - If Mode of Payment doesn't exist, create it with the account
    - If it exists but has no accounts table row for company, add the row
    - If it exists and already has the company row, do nothing
    - If account is None, skip creation/update and raise clear error

    Args:
        frappe: Frappe context
        mode_name: Mode of Payment name (e.g. "Cash", "Whish Money")
        payment_type: Frappe payment type (e.g. "Bank", "Cash")
        company_name: Target company name
        account_name: Default account for this mode/company pair

    Returns:
        {"created": mode_name, "account": account_name}  or
        {"upserted": mode_name, "account": account_name}  or
        {"skipped": mode_name, "reason": "account already configured"}

    Raises:
        ValueError: if account_name is None
    """
    if not account_name:
        raise ValueError(
            f"Cannot create Mode of Payment '{mode_name}': "
            f"no suitable account found for company '{company_name}'. "
            f"Ensure the company has at least one {payment_type}-type account."
        )

    mop_exists = frappe.db.exists("Mode of Payment", mode_name)

    if mop_exists:
        # Fetch the existing Mode of Payment and check accounts table
        mop = frappe.get_doc("Mode of Payment", mode_name)

        # Check if company already has an account configured
        company_already_configured = any(
            acc.company == company_name
            for acc in (mop.accounts or [])
        )

        if company_already_configured:
            # Already configured for this company; skip
            return {"skipped": mode_name, "reason": "account already configured"}

        # Mode exists but needs company account row; add it
        mop.append("accounts", {
            "company": company_name,
            "default_account": account_name,
        })
        mop.save(ignore_permissions=True)
        frappe.db.commit()
        return {"upserted": mode_name, "account": account_name}

    # Mode doesn't exist; create it from scratch
    mop = frappe.get_doc({
        "doctype": "Mode of Payment",
        "mode_of_payment": mode_name,
        "type": payment_type,
        "accounts": [{"company": company_name, "default_account": account_name}],
    })
    mop.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"created": mode_name, "account": account_name}


def _create_mode_of_payment(frappe, company_name: str, company_abbr: str) -> dict:
    """Configure all FitDesk payment methods (Cash, Bank Transfer, Whish Money).

    Creates or updates Mode of Payment records for the three payment methods
    FitDesk exposes to trainers. All are idempotent.

    Returns:
        {
            "modes": {
                "Cash": {...},
                "Bank Transfer": {...},
                "Whish Money": {...},
            }
        }
    """
    results: dict[str, dict] = {}

    # Cash: require Cash account type only (no fallback for accounting safety)
    cash_account = _get_account_for_company(frappe, company_name, "Cash")
    if not cash_account:
        raise ValueError(
            f"Cannot configure Cash mode: company '{company_name}' has no Cash account. "
            "Check ERPNext Chart of Accounts and ensure a Cash-type account exists."
        )
    results["Cash"] = _upsert_mode_of_payment(
        frappe, "Cash", "Cash", company_name, cash_account
    )

    # Bank Transfer: require Bank account type only (no fallback for accounting safety)
    bank_account = _get_account_for_company(frappe, company_name, "Bank")
    if not bank_account:
        raise ValueError(
            f"Cannot configure Bank Transfer mode: company '{company_name}' has no Bank account. "
            "Check ERPNext Chart of Accounts and ensure a Bank-type account exists."
        )
    results["Bank Transfer"] = _upsert_mode_of_payment(
        frappe, "Bank Transfer", "Bank", company_name, bank_account
    )

    # Whish Money: try Bank account, fall back to Cash (preserve existing behavior)
    whish_account = _get_account_for_company(frappe, company_name, "Bank", "Cash")
    if not whish_account:
        raise ValueError(
            f"Cannot configure Whish Money mode: company '{company_name}' has no Bank or Cash account. "
            "Check ERPNext Chart of Accounts."
        )
    results["Whish Money"] = _upsert_mode_of_payment(
        frappe, "Whish Money", "Bank", company_name, whish_account
    )

    return {"modes": results}


# ── Sub-function 7: WhatsApp Server Script ────────────────────────────────────

def _create_whatsapp_server_script(
    frappe,
    control_plane_webhook_url: str,
    control_plane_webhook_secret: str,
    tenant_slug: str = "",
) -> dict:
    """Create the Server Script that fires on Sales Invoice submission.

    The script POSTs invoice details to the control-plane webhook, which
    generates a Whish Money payment link and sends it via WhatsApp.

    The webhook URL and per-tenant secret are baked into the script body at
    provisioning time — no runtime env vars required inside Frappe.

    Idempotent: returns {"skipped": True} if the script already exists.

    Returns:
        {"skipped": True}  or  {"server_script": "FitDesk Invoice Submit Webhook"}
    """
    if frappe.db.exists("Server Script", "FitDesk Invoice Submit Webhook"):
        return {"skipped": True}

    # Use frappe.make_post_request (available in safe_exec frappe namespace).
    # Note: top-level `import` and `frappe.conf` are not available in
    # Frappe's RestrictedPython sandbox (safe_exec).  The tenant_slug is
    # baked in at provisioning time to avoid a runtime conf lookup.
    _slug = (tenant_slug or frappe.local.site or "").strip("/")
    script_code = f"""doc = frappe.get_doc("Sales Invoice", doc.name)
if not doc.custom_whatsapp_sent:
    payload = {{
        "event": "invoice_submitted",
        "invoice_name": doc.name,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "grand_total": doc.grand_total,
        "custom_session_date": str(doc.custom_session_date or ""),
        "tenant_slug": "{_slug}",
    }}
    try:
        frappe.make_post_request(
            "{control_plane_webhook_url}",
            json=payload,
            headers={{"X-Webhook-Secret": "{control_plane_webhook_secret}"}},
        )
        frappe.db.set_value("Sales Invoice", doc.name,
                            "custom_whatsapp_sent", 1)
    except Exception as e:
        frappe.log_error(str(e), "FitDesk Webhook")
"""

    ss = frappe.get_doc({
        "doctype": "Server Script",
        "name": "FitDesk Invoice Submit Webhook",
        "script_type": "DocType Event",
        "reference_doctype": "Sales Invoice",
        "doctype_event": "After Submit",
        "script": script_code,
        "disabled": 1,   # invoice payment requests require explicit trainer action
    })
    ss.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"server_script": "FitDesk Invoice Submit Webhook"}


# ── Sub-function 9: Enable Server Scripts ─────────────────────────────────────

def _enable_server_scripts(frappe) -> dict:
    """Enable server scripts via common_site_config.json.

    In Frappe v15, server_script_enabled is a common site config key (not a
    System Settings field).  We write it directly to common_site_config.json
    so it is available globally.

    Idempotent: no-op if already enabled.

    Returns:
        {"skipped": True} if already enabled, {"enabled": True} if just set.
    """
    if frappe.get_common_site_config().get("server_script_enabled"):
        return {"skipped": True}

    import json
    import os

    sites_path = frappe.utils.get_sites_path()
    config_path = os.path.join(sites_path, "common_site_config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}

    config["server_script_enabled"] = True

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=1)

    return {"enabled": True}


# ── Sub-function 8: Price Lists ───────────────────────────────────────────────

def _create_price_lists(frappe) -> dict:
    """Create Standard Selling and Standard Buying price lists if they don't exist.

    ERPNext's setup wizard normally creates these.  Without them Sales Invoices
    fail with a mandatory selling_price_list validation error.

    Returns:
        {"created": [...names...], "skipped": [...names...]}
    """
    created = []
    skipped = []

    for name, is_buying, is_selling in [
        ("Standard Selling", 0, 1),
        ("Standard Buying",  1, 0),
    ]:
        if frappe.db.exists("Price List", name):
            skipped.append(name)
            continue
        pl = frappe.get_doc({
            "doctype": "Price List",
            "price_list_name": name,
            "selling": is_selling,
            "buying": is_buying,
            "enabled": 1,
            "currency": frappe.db.get_single_value("Global Defaults", "default_currency") or "USD",
        })
        pl.insert(ignore_permissions=True)
        created.append(name)

    if created:
        frappe.db.commit()
        # Wire selling price list into Selling Settings
        try:
            ss = frappe.get_single("Selling Settings")
            if not ss.selling_price_list:
                ss.selling_price_list = "Standard Selling"
                ss.save(ignore_permissions=True)
                frappe.db.commit()
        except Exception:  # noqa: BLE001
            pass

    return {"created": created, "skipped": skipped}


# ── E2E Verification ──────────────────────────────────────────────────────────

def verify_fitdesk_schema(company_name: str) -> dict:
    """Verify FitDesk schema exists after setup.

    Call after setup_fitdesk_schema to confirm all records were created.

    Core ``ok`` requires the 4 billing-critical custom fields, TRAINING-SESSION
    item, Customer Group Individual, and Standard Selling price list.

    Mode of Payment records are advisory: they are only needed for the Paid Now
    path and must not block tenants whose Chart of Accounts is incomplete or
    who exclusively use Pay Later / PPS invoice flows.

    Returns:
        {
            "ok": <bool>,
            "checks": {
                "custom_fields": <int>,               # total custom fields present (max 15)
                "core_billing_fields": <int>,          # required billing fields present (max 4)
                "training_item": <bool>,
                "customer_group": <bool>,
                "print_format": <bool>,                # advisory — cosmetic only
                "price_list_standard_selling": <bool>, # required for invoice submission
                "mode_of_payment_cash": <bool>,        # advisory — paid-now path only
                "mode_of_payment_bank_transfer": <bool>,  # advisory — paid-now path only
                "mode_of_payment_whish": <bool>,       # advisory — paid-now path only
                "server_script": <bool>,               # advisory — WhatsApp webhook only
            }
        }
    """
    import frappe  # lazy

    # The 4 custom fields the new billing model strictly requires.
    _REQUIRED_BILLING_FIELDNAMES = [
        "custom_billing_mode",
        "custom_default_session_rate",
        "custom_fd_session",
        "custom_invoice_kind",
    ]

    checks: dict = {}

    # Total custom field count (observability — all 15 known fields)
    checks["custom_fields"] = frappe.db.count(
        "Custom Field",
        {
            "dt": ["in", ["Customer", "Sales Invoice"]],
            "fieldname": ["in", [
                "custom_fitness_goals",
                "custom_trainer_notes",
                "custom_package_type",
                "custom_remaining_sessions",
                "custom_session_date",
                "custom_session_time",
                "custom_no_show",
                "custom_whatsapp_sent",
                "custom_payment_link",
                "custom_payment_reference",
                "custom_billing_mode",
                "custom_default_session_rate",
                "custom_package_name",
                "custom_fd_session",
                "custom_invoice_kind",
            ]],
        },
    )

    # Subset check — only the 4 billing-critical fields gate core readiness
    checks["core_billing_fields"] = frappe.db.count(
        "Custom Field",
        {
            "dt": ["in", ["Customer", "Sales Invoice"]],
            "fieldname": ["in", _REQUIRED_BILLING_FIELDNAMES],
        },
    )

    checks["training_item"] = bool(frappe.db.exists("Item", "TRAINING-SESSION"))
    checks["customer_group"] = bool(frappe.db.exists("Customer Group", "Individual"))
    checks["print_format"] = bool(frappe.db.exists("Print Format", "FitDesk Invoice"))
    checks["price_list_standard_selling"] = bool(frappe.db.exists("Price List", "Standard Selling"))

    # Advisory — included for observability but do not affect ok
    checks["mode_of_payment_cash"] = bool(frappe.db.exists("Mode of Payment", "Cash"))
    checks["mode_of_payment_bank_transfer"] = bool(frappe.db.exists("Mode of Payment", "Bank Transfer"))
    checks["mode_of_payment_whish"] = bool(frappe.db.exists("Mode of Payment", "Whish Money"))
    checks["server_script"] = bool(frappe.db.exists("Server Script", "FitDesk Invoice Submit Webhook"))

    all_ok = (
        checks["core_billing_fields"] == len(_REQUIRED_BILLING_FIELDNAMES)
        and checks["training_item"]
        and checks["customer_group"]
        and checks["price_list_standard_selling"]
        # print_format: cosmetic — advisory only
        # mode_of_payment_*: paid-now path only — advisory
        # server_script: WhatsApp webhook only — advisory
    )
    return {"ok": all_ok, "checks": checks}
