"""Locale / system-settings bootstrap invoked by bench-agent via `bench execute`.

Runs early in the provisioning sequence — before Company creation — to ensure
System Settings is fully configured before any transactional doctype is touched.

Why this lives here (not in bench-agent directly):
    - Enabling a Currency and saving System Settings requires the Frappe ORM,
      which is only available inside a live Frappe runtime.
    - bench-agent shells out to
      `bench --site <site> execute provisioning_api.api.bootstrap.setup_locale`
      which spins up a Frappe environment for us.

Contract with bench-agent:
    The function prints TWO lines to stdout on success, parsed by
    `axis_bench_agent.bench._parse_locale_result`:

        currency=<ISO-code>
        timezone=<IANA-tz>

    Any other stdout is ignored.  On failure the function raises, which
    makes `bench execute` exit non-zero and bench-agent classifies it as a
    BenchCommandError.
"""

from __future__ import annotations


# Static ISO-3166-1 alpha-2 → Frappe Country name map.
# Frappe's tabCountry `name` is the full English country name; `code` is
# the lowercase 2-letter ISO code.  We maintain a fast local lookup for the
# most common deployment targets and fall back to a DB query for the rest.
_ISO2_TO_COUNTRY_NAME: dict[str, str] = {
    "ae": "United Arab Emirates",
    "us": "United States",
    "gb": "United Kingdom",
    "in": "India",
    "sa": "Saudi Arabia",
    "om": "Oman",
    "qa": "Qatar",
    "kw": "Kuwait",
    "bh": "Bahrain",
    "eg": "Egypt",
    "de": "Germany",
    "fr": "France",
    "it": "Italy",
    "es": "Spain",
    "nl": "Netherlands",
    "be": "Belgium",
    "ch": "Switzerland",
    "at": "Austria",
    "se": "Sweden",
    "no": "Norway",
    "dk": "Denmark",
    "fi": "Finland",
    "ie": "Ireland",
    "pt": "Portugal",
    "gr": "Greece",
    "pl": "Poland",
    "cz": "Czech Republic",
    "hu": "Hungary",
    "ro": "Romania",
    "au": "Australia",
    "nz": "New Zealand",
    "ca": "Canada",
    "za": "South Africa",
    "ng": "Nigeria",
    "ke": "Kenya",
    "pk": "Pakistan",
    "bd": "Bangladesh",
    "lk": "Sri Lanka",
    "sg": "Singapore",
    "my": "Malaysia",
    "ph": "Philippines",
    "id": "Indonesia",
    "jp": "Japan",
    "cn": "China",
    "br": "Brazil",
    "mx": "Mexico",
    "ar": "Argentina",
    "tr": "Turkey",
    "ru": "Russia",
    "il": "Israel",
    "th": "Thailand",
    "vn": "Vietnam",
    "np": "Nepal",
}


def setup_locale(
    country: str,
    default_currency: str,
    timezone: str,
    language: str = "en",
    date_format: str = "dd-mm-yyyy",
    currency_precision: int = 2,
    company_name: str = "",
) -> dict:
    """Enable the tenant currency and configure System Settings locale.

    Idempotency:
        - Currency: sets enabled=1 if found; harmless no-op if already enabled.
        - System Settings: overwrites with the supplied values each call; the
          result is identical on retry so this is safe to call more than once.

    Args:
        country:      ISO 3166-1 alpha-2 code (e.g. "AE", "US", "IN").
        default_currency: ISO 4217 code (e.g. "AED", "USD", "INR").
        timezone:     IANA timezone string (e.g. "Asia/Dubai", "America/New_York").
        language:     BCP-47 language code matching a Frappe Language record (default "en").
        date_format:  Frappe date format string (default "dd-mm-yyyy").
        currency_precision: Number of decimal places 0-9 (default 2).
        company_name: Reserved for future use (Company creation step).

    Raises:
        ValueError:              if required arguments are missing or invalid type.
        frappe.DoesNotExistError: if the currency code is not in tabCurrency.
    """
    # Validate before importing frappe so errors surface clearly even outside
    # a live Frappe runtime (e.g. during unit tests of this module).
    if not country or not isinstance(country, str):
        raise ValueError("country is required")
    if not default_currency or not isinstance(default_currency, str):
        raise ValueError("default_currency is required")
    if not timezone or not isinstance(timezone, str):
        raise ValueError("timezone is required")

    country = country.strip().upper()
    default_currency = default_currency.strip().upper()
    _ = company_name  # reserved for future Company-creation step
    timezone = timezone.strip()
    language = (language or "en").strip()
    date_format = (date_format or "dd-mm-yyyy").strip()
    currency_precision = int(currency_precision)  # guard against float from JSON

    import frappe  # lazy — only available under `bench execute`

    # ── 1. Enable currency ─────────────────────────────────────────────────
    if not frappe.db.exists("Currency", default_currency):
        raise frappe.exceptions.DoesNotExistError(
            f"Currency '{default_currency}' does not exist in tabCurrency. "
            "Use a valid ISO 4217 currency code."
        )

    currency_doc = frappe.get_doc("Currency", default_currency)
    if not currency_doc.enabled:
        currency_doc.enabled = 1
        currency_doc.save(ignore_permissions=True)
        frappe.db.commit()

    # ── 2. Resolve ISO-2 country code → Frappe Country name ───────────────
    country_name: str | None = _ISO2_TO_COUNTRY_NAME.get(country.lower())
    if not country_name:
        # Fall back to a DB lookup via the `code` field on tabCountry.
        country_name = frappe.db.get_value("Country", {"code": country.lower()}, "name")
    if not country_name:
        # Last resort: pass through as-is and let Frappe validate the link.
        country_name = country

    # ── 3. Configure System Settings ───────────────────────────────────────
    system_settings = frappe.get_single("System Settings")
    system_settings.language = language
    system_settings.time_zone = timezone
    system_settings.date_format = date_format
    # currency_precision is a Select field in Frappe (stored as string "0"–"9").
    system_settings.currency_precision = str(currency_precision)
    system_settings.country = country_name
    system_settings.save(ignore_permissions=True)
    frappe.db.commit()

    # bench-agent parses these two lines from stdout.
    print(f"currency={default_currency}")
    print(f"timezone={timezone}")

    return {
        "ok": True,
        "currency": default_currency,
        "timezone": timezone,
        "country": country_name,
        "language": language,
    }


_DEFAULT_WAREHOUSE_TYPES = [
    "Transit",
    "Finished Goods",
    "Work In Progress",
    "Raw Material",
    "Stores",
]


def _ensure_warehouse_types(frappe) -> None:
    """Create default Warehouse Type records if missing.

    ERPNext's create_default_warehouses() hook references these by name.
    They are normally created by the setup wizard, but our provisioning flow
    skips the wizard — so we seed them here if absent.
    """
    for wt_name in _DEFAULT_WAREHOUSE_TYPES:
        if not frappe.db.exists("Warehouse Type", wt_name):
            wt_doc = frappe.new_doc("Warehouse Type")
            wt_doc.name = wt_name
            wt_doc.insert(ignore_permissions=True)
    frappe.db.commit()


def setup_company(
    company_name: str,
    company_abbr: str,
    country: str,
    default_currency: str,
    company_type: str = "Company",
    domain: str = "Services",
) -> dict:
    """Create the Company document via the Frappe ORM.

    Uses ``doc.insert()`` (not ``frappe.db.insert``) so that after_insert hooks
    fire and build the Chart of Accounts, default warehouses, and cost centers.

    Idempotency:
        If a Company with ``company_name`` already exists, returns immediately
        with ``{"ok": True, "skipped": True}``.  Safe to call on retry.

    Args:
        company_name:     Full legal company name (e.g. "Test Fitness LLC").
        company_abbr:     Short abbreviation used as account suffix (e.g. "TF").
        country:          ISO 3166-1 alpha-2 code (e.g. "AE") — resolved to
                          the Frappe Country name internally.
        default_currency: ISO 4217 code (e.g. "AED").
        company_type:     Frappe Company Type field (default "Company").
        domain:           Frappe domain (e.g. "Services", "Manufacturing").

    Raises:
        ValueError:   if required args are missing.
        RuntimeError: if CoA was not built after insert (0 accounts).
    """
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")
    if not company_abbr or not isinstance(company_abbr, str):
        raise ValueError("company_abbr is required")
    if not country or not isinstance(country, str):
        raise ValueError("country is required")
    if not default_currency or not isinstance(default_currency, str):
        raise ValueError("default_currency is required")

    company_name = company_name.strip()
    company_abbr = company_abbr.strip()
    country = country.strip().upper()
    default_currency = default_currency.strip().upper()

    import frappe  # lazy — only available under `bench execute`

    # ── Idempotency guard ──────────────────────────────────────────────────
    if frappe.db.exists("Company", company_name):
        account_count = frappe.db.count("Account", {"company": company_name})
        print(f"company={company_name}")
        print(f"account_count={account_count}")
        print("skipped=true")
        return {"ok": True, "skipped": True, "company": company_name, "account_count": account_count}

    # ── Resolve ISO-2 country code → Frappe Country name ──────────────────
    country_name: str | None = _ISO2_TO_COUNTRY_NAME.get(country.lower())
    if not country_name:
        country_name = frappe.db.get_value("Country", {"code": country.lower()}, "name")
    if not country_name:
        country_name = country  # pass-through; Frappe validates the link

    # ── Ensure Warehouse Types exist (created by setup wizard; needed for hooks) ──
    _ensure_warehouse_types(frappe)

    # ── Insert Company (triggers after_insert CoA / warehouse hooks) ───────
    doc = frappe.get_doc({
        "doctype": "Company",
        "company_name": company_name,
        "abbr": company_abbr,
        "country": country_name,
        "default_currency": default_currency,
        "company_type": company_type,
        "domain": domain,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    # ── Verify CoA was built ───────────────────────────────────────────────
    account_count = frappe.db.count("Account", {"company": company_name})
    if account_count == 0:
        raise RuntimeError(
            f"Company '{company_name}' inserted but Chart of Accounts was not created. "
            "Verify ERPNext is fully installed and the country has a default CoA template."
        )

    print(f"company={company_name}")
    print(f"account_count={account_count}")
    return {"ok": True, "skipped": False, "company": company_name, "account_count": account_count}


def setup_fiscal_year(
    company_name: str,
    fiscal_year_start_month: int = 1,
    company_abbr: str = "",
) -> dict:
    """Create the Fiscal Year document and link it to the company.

    Derives FY dates from ``fiscal_year_start_month`` and today's date:
    - If today >= start_month this year  → FY started this year.
    - If today <  start_month this year  → FY started last year.

    Idempotent: if a FY with the same name already exists, the company is
    added to its ``companies`` child table if absent, and returns immediately.

    Args:
        company_name:            Full company name (e.g. "Test Fitness LLC").
        fiscal_year_start_month: 1–12 (default 1 = January = calendar year).
        company_abbr:            Reserved; not used directly.

    Stdout contract (parsed by bench-agent):
        fiscal_year=<name>
        start=<YYYY-MM-DD>
        end=<YYYY-MM-DD>
    """
    from datetime import date, timedelta

    _ = company_abbr  # reserved
    month = int(fiscal_year_start_month)
    if not 1 <= month <= 12:
        raise ValueError(f"fiscal_year_start_month must be 1-12, got {month}")
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")

    import frappe  # lazy — only available under `bench execute`

    today = date.today()

    # Determine FY start date
    start_this_year = date(today.year, month, 1)
    if today >= start_this_year:
        fy_start = start_this_year
    else:
        fy_start = date(today.year - 1, month, 1)

    # FY end = one day before the next FY starts
    next_fy_start = date(fy_start.year + 1, month, 1)
    fy_end = next_fy_start - timedelta(days=1)

    # FY name convention: "2026" for January-start, "2026-2027" otherwise
    fy_name = str(fy_start.year) if month == 1 else f"{fy_start.year}-{fy_end.year}"

    # ── Idempotency ────────────────────────────────────────────────────────
    if frappe.db.exists("Fiscal Year", fy_name):
        fy_doc = frappe.get_doc("Fiscal Year", fy_name)
        existing_companies = [c.company for c in fy_doc.get("companies", [])]
        if company_name not in existing_companies:
            fy_doc.append("companies", {"company": company_name})
            fy_doc.save(ignore_permissions=True)
            frappe.db.commit()
        print(f"fiscal_year={fy_name}")
        print(f"start={fy_start}")
        print(f"end={fy_end}")
        print("skipped=true")
        return {"ok": True, "skipped": True, "fiscal_year": fy_name,
                "start": str(fy_start), "end": str(fy_end)}

    # ── Create Fiscal Year ─────────────────────────────────────────────────
    doc = frappe.get_doc({
        "doctype": "Fiscal Year",
        "year": fy_name,
        "year_start_date": str(fy_start),
        "year_end_date": str(fy_end),
        "is_default": 1,
        "companies": [{"company": company_name}],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    print(f"fiscal_year={fy_name}")
    print(f"start={fy_start}")
    print(f"end={fy_end}")
    return {"ok": True, "skipped": False, "fiscal_year": fy_name,
            "start": str(fy_start), "end": str(fy_end)}


def setup_global_defaults(
    company_name: str,
    default_currency: str,
    fiscal_year_name: str,
    country: str,
) -> dict:
    """Configure Global Defaults singleton.

    Sets ``default_company``, ``default_currency``, ``country``,
    and ``current_fiscal_year`` so workspace cards render correctly.

    Idempotent: overwrites with the same values on retry.

    Args:
        company_name:      Full company name (e.g. "Test Fitness LLC").
        default_currency:  ISO 4217 code (e.g. "AED").
        fiscal_year_name:  Frappe Fiscal Year name (e.g. "2026" or "2026-2027").
        country:           ISO 3166-1 alpha-2 code (e.g. "AE").

    Stdout contract:
        ok=true
    """
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")
    if not default_currency or not isinstance(default_currency, str):
        raise ValueError("default_currency is required")
    if not fiscal_year_name or not isinstance(fiscal_year_name, str):
        raise ValueError("fiscal_year_name is required")
    if not country or not isinstance(country, str):
        raise ValueError("country is required")

    import frappe  # lazy — only available under `bench execute`

    country = country.strip().upper()
    country_name: str | None = _ISO2_TO_COUNTRY_NAME.get(country.lower())
    if not country_name:
        country_name = frappe.db.get_value("Country", {"code": country.lower()}, "name")
    if not country_name:
        country_name = country

    gd = frappe.get_single("Global Defaults")
    gd.default_company = company_name
    gd.default_currency = default_currency.strip().upper()
    gd.country = country_name
    gd.current_fiscal_year = fiscal_year_name
    gd.hide_currency_symbol = 0
    gd.save(ignore_permissions=True)
    frappe.db.commit()

    print("ok=true")
    return {"ok": True}


def setup_complete(company_name: str) -> dict:
    """Set System Settings.setup_complete = 1 to bypass the setup wizard.

    This is the final gate before the tenant can reach /desk. It runs ONLY
    after Steps 1–3 are confirmed complete and verifies preconditions before
    setting the flag. Setting the flag on incomplete data causes crashes on
    the first Frappe transaction.

    Precondition checks:
        1. System Settings.country is set (locale_configured ran).
        2. At least one Account exists for the company (company_created ran).
        3. At least one Fiscal Year exists (fiscal_year_created ran).
        4. Global Defaults.default_company == company_name (global_defaults_set ran).

    Idempotent: if setup_complete is already 1, returns skipped=True immediately.

    Args:
        company_name: Full company name (e.g. "Test Fitness LLC").

    Raises:
        ValueError:   if company_name is missing.
        RuntimeError: if any precondition check fails.

    Stdout contract:
        setup_complete=true
    """
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name is required")

    import frappe  # lazy — only available under `bench execute`

    # ── Idempotency guard ──────────────────────────────────────────────────
    if frappe.db.get_single_value("System Settings", "setup_complete"):
        print("setup_complete=true")
        print("skipped=true")
        return {"ok": True, "setup_complete": True, "skipped": True}

    # ── Precondition: locale was configured ───────────────────────────────
    if not frappe.db.get_single_value("System Settings", "country"):
        raise RuntimeError(
            "Precondition failed: System Settings.country is not set. "
            "Ensure locale_configured step ran successfully before setup_complete."
        )

    # ── Precondition: Chart of Accounts was built ─────────────────────────
    account_count = frappe.db.count("Account", {"company": company_name})
    if account_count == 0:
        raise RuntimeError(
            f"Precondition failed: no Accounts found for company '{company_name}'. "
            "Ensure company_created step ran successfully before setup_complete."
        )

    # ── Precondition: Fiscal Year exists ─────────────────────────────────
    fy_count = frappe.db.count("Fiscal Year")
    if fy_count == 0:
        raise RuntimeError(
            "Precondition failed: no Fiscal Year documents found. "
            "Ensure fiscal_year_created step ran successfully before setup_complete."
        )

    # ── Precondition: Global Defaults points to this company ─────────────
    gd_company = frappe.db.get_single_value("Global Defaults", "default_company")
    if gd_company != company_name:
        raise RuntimeError(
            f"Precondition failed: Global Defaults.default_company is '{gd_company}', "
            f"expected '{company_name}'. "
            "Ensure global_defaults_set step ran successfully before setup_complete."
        )

    # ── Set setup wizard bypass flag + enable server scripts ─────────────
    default_currency = frappe.db.get_single_value("Global Defaults", "default_currency") or ""

    system_settings = frappe.get_single("System Settings")
    system_settings.setup_complete = 1
    system_settings.allow_server_scripts = 1  # required for FitDesk Server Script
    if default_currency:
        system_settings.default_currency = default_currency
    system_settings.save(ignore_permissions=True)
    frappe.db.commit()

    print("setup_complete=true")
    return {"ok": True, "setup_complete": True, "skipped": False}
