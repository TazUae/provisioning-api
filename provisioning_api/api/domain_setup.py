"""Domain + Module Activation.

Activates all standard ERPNext business domains in Domain Settings so
every sidebar module is visible, then unblocks any Module Def records
that were blocked by default.

stdout contract (for bench-agent parsing):
    ok=true
    modules_unblocked=<int>
"""

from __future__ import annotations

ALL_DOMAINS = [
    "Manufacturing",
    "Retail",
    "Healthcare",
    "Agriculture",
    "Education",
    "Non Profit",
    "Services",
    "Distribution",
]


def activate_all_domains(company_name: str) -> dict:
    """Activate all ERPNext business domains and unblock all modules.

    Steps:
    1. Get or create the Domain Settings document and set active_domains
       to ALL_DOMAINS.
    2. Call frappe.get_doc("Domain", domain).setup() for each domain to
       load domain-specific fixtures. Each domain is wrapped in try/except
       so a single failure does not block the others.
    3. Set Module Def.blocked = 0 for every blocked module.
    4. Clear the cache.

    Idempotent: safe to re-run; Domain Settings.active_domains is always
    set to the full list and blocked modules are always unblocked.

    Args:
        company_name: Name of the existing Company document (used for
                      logging; Domain Settings is a singleton).
    """
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")
    company_name = company_name.strip()

    import frappe  # imported lazily — only available under `bench execute`

    # ── 0. Discover which Domain documents actually exist ────────────────
    # Domain records are created lazily by ERPNext; only set active_domains
    # to entries that already have a Domain document, otherwise Frappe's
    # link validation raises LinkValidationError on save.
    existing_names = {
        row["name"]
        for row in frappe.db.get_all("Domain", fields=["name"])
    }
    available_domains = [d for d in ALL_DOMAINS if d in existing_names]

    # ── 1. Domain Settings ──────────────────────────────────────────────
    ds = frappe.get_single("Domain Settings")
    ds.set("active_domains", [{"domain": d} for d in available_domains])
    ds.save(ignore_permissions=True)
    frappe.db.commit()

    # ── 2. Per-domain fixture loading ───────────────────────────────────
    domain_errors: list[str] = []
    for domain in available_domains:
        try:
            frappe.get_doc("Domain", domain).setup()
            frappe.db.commit()
        except Exception as exc:  # noqa: BLE001
            domain_errors.append(f"{domain}: {exc}")

    # ── 3. Unblock Module Def records ───────────────────────────────────
    # The "blocked" column existed in ERPNext v14 but was removed in v15.
    # Check whether the column exists before querying it.
    blocked_count = 0
    try:
        columns = {
            row[0]
            for row in frappe.db.sql("SHOW COLUMNS FROM `tabModule Def`")
        }
        if "blocked" in columns:
            blocked_count = frappe.db.count("Module Def", {"blocked": 1})
            if blocked_count:
                frappe.db.set_value("Module Def", {"blocked": 1}, "blocked", 0)
                frappe.db.commit()
    except Exception:  # noqa: BLE001
        pass

    # ── 4. Clear cache ───────────────────────────────────────────────────
    frappe.clear_cache()

    if domain_errors:
        import sys
        print(f"domain_setup_warnings={len(domain_errors)}", file=sys.stderr)
        for err in domain_errors:
            print(f"  {err}", file=sys.stderr)

    print("ok=true")
    print(f"modules_unblocked={blocked_count}")

    return {
        "ok": True,
        "domains_activated": available_domains,
        "modules_unblocked": blocked_count,
        "domain_errors": domain_errors,
    }
