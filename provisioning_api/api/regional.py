"""Regional setup: run ERPNext's country-specific localization module.

Why this lives in its own file (not bootstrap.py):
    - Regional setup is optional and always succeeds — even if the module
      does not exist or raises. Keeping it separate prevents a non-fatal
      step from cluttering the critical-path bootstrap module.

stdout contract (for bench-agent parsing):
    ok=true
    regional=true          ← module was found and executed
  or:
    ok=true
    regional=false         ← no module / module failed; placeholder tax created
    reason=<short message>
"""

from __future__ import annotations


def setup_regional(country: str, company_name: str, company_abbr: str = "") -> dict:
    """Run ERPNext's regional localization module if one exists for *country*.

    Always exits 0.  If the regional module is absent or raises, a generic
    0% Sales Tax Item Tax Template is created as a placeholder so the site
    has at least one tax template ready for invoicing.

    Args:
        country:      ISO 3166-1 alpha-2 code (e.g. "AE", "US").
        company_name: Name of the existing Company document.
        company_abbr: Abbreviation (optional; unused but kept for symmetry
                      with other provisioning functions).
    """
    if not country or not isinstance(country, str):
        raise ValueError("country is required")
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")
    country = country.strip().upper()
    company_name = company_name.strip()

    import frappe  # imported lazily — only available under `bench execute`

    country_slug = _country_code_to_slug(frappe, country)
    if country_slug is None:
        reason = f"no ERPNext country mapping for ISO code {country!r}"
        _create_placeholder_tax(frappe, company_name)
        print("ok=true")
        print("regional=false")
        print(f"reason={reason}")
        return {"ok": True, "regional": False, "reason": reason}

    module_path = f"erpnext.regional.{country_slug}.setup"
    try:
        import importlib
        mod = importlib.import_module(module_path)
        if hasattr(mod, "setup"):
            mod.setup()
        frappe.db.commit()
        print("ok=true")
        print("regional=true")
        return {"ok": True, "regional": True}
    except ModuleNotFoundError:
        reason = f"no regional module at {module_path}"
        _create_placeholder_tax(frappe, company_name)
        print("ok=true")
        print("regional=false")
        print(f"reason={reason}")
        return {"ok": True, "regional": False, "reason": reason}
    except Exception as exc:  # noqa: BLE001  — regional modules can raise anything
        reason = f"regional module {module_path} raised: {exc}"
        try:
            frappe.db.rollback()
        except Exception:  # noqa: BLE001
            pass
        _create_placeholder_tax(frappe, company_name)
        print("ok=true")
        print("regional=false")
        print(f"reason={reason}")
        return {"ok": True, "regional": False, "reason": reason}


def _country_code_to_slug(frappe, iso_code: str) -> str | None:
    """Map an ISO 3166-1 alpha-2 code to an ERPNext regional module slug.

    ERPNext regional module directories are snake_cased versions of the
    country's full English name as stored in Frappe's Country doctype.
    """
    country_name = frappe.db.get_value("Country", {"code": iso_code.lower()}, "name")
    if not country_name:
        return None
    slug = country_name.strip().lower().replace(" ", "_").replace("-", "_")
    return slug


def _create_placeholder_tax(frappe, company_name: str) -> None:
    """Create a generic 0% Sales Tax Item Tax Template if none exist.

    Ensures the site has at least one tax template so the UI does not
    force the user through a tax-setup wizard before creating invoices.
    Idempotent: skips creation if any Item Tax Template already exists.
    """
    existing = frappe.db.count(
        "Item Tax Template", {"company": company_name, "disabled": 0}
    )
    if existing > 0:
        return

    try:
        doc = frappe.get_doc(
            {
                "doctype": "Item Tax Template",
                "title": "Sales Tax",
                "company": company_name,
                "taxes": [],  # 0% — empty rows means no tax applied
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:  # noqa: BLE001  — non-fatal
        try:
            frappe.db.rollback()
        except Exception:  # noqa: BLE001
            pass
