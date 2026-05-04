"""Post-provisioning smoke test.

Verifies the newly provisioned ERP instance is fully functional by running a
real transaction sequence using the provisioned API user's credentials (not
Administrator). This catches silent failures in CoA, company, permissions, or
regional setup that a simple health-check cannot detect.

Called by bench-agent via:
    bench --site <site> execute \\
        provisioning_api.api.smoke_test.run_smoke_test \\
        --kwargs '{"company_name":..., "api_key":..., "api_secret":...,
                   "site_url":..., "site":...}'

Stdout contract (parsed by bench-agent _parse_smoke_result):
    Success:  ok=true\\nsmoke_test=passed\\ntests_run=<comma-list>
    Failure:  ok=false\\nfailed_at=<step>\\nerror=<message>

    On failure bench-agent raises BenchCommandError; the control plane marks
    smoke_test_passed as a retriable step failure.
"""

from __future__ import annotations

_SMOKE_CUSTOMER = "__smoke_test_customer__"


class _SmokeTestError(Exception):
    def __init__(self, failed_at: str, error: str) -> None:
        super().__init__(error)
        self.failed_at = failed_at


def select_smoke_customer_group(frappe) -> str | None:
    """Pick a Customer Group that may be set on Customer (leaf only: ``is_group == 0``).

    Prefer stable names used by typical ERPNext / FitDesk setups. Never picks the
    tree root ``All Customer Groups`` unless it appears as a fallback row with
    ``is_group == 0`` (not normal).
    """
    for name in ("Individual", "Commercial", "Default"):
        if not frappe.db.exists("Customer Group", name):
            continue
        is_group = frappe.db.get_value("Customer Group", name, "is_group")
        if is_group == 1:
            continue
        if is_group == 0:
            return name
    rows = frappe.db.get_all(
        "Customer Group",
        filters={"is_group": 0},
        pluck="name",
        limit=1,
    )
    return rows[0] if rows else None


def run_smoke_test(
    company_name: str,
    api_key: str,
    api_secret: str,
    site_url: str,
    site: str,
) -> dict:
    """Run transaction smoke test using provisioned API credentials.

    Makes HTTP requests to the Frappe REST API (via site_url + Host: site)
    to verify the full stack end-to-end. Also uses the Frappe ORM (available
    inside ``bench execute``) for data discovery.
    """
    import requests
    import frappe  # available inside bench execute runtime

    base = site_url.rstrip("/")
    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Host": site,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    tests_run: list[str] = []
    customer_name: str | None = None
    invoice_name: str | None = None

    def _get(path: str):
        return requests.get(f"{base}{path}", headers=headers, timeout=30)

    def _post(path: str, data: dict):
        return requests.post(f"{base}{path}", json=data, headers=headers, timeout=30)

    def _delete(path: str):
        return requests.delete(f"{base}{path}", headers=headers, timeout=30)

    try:
        # ── 1. Verify API credentials are accepted ─────────────────────────
        resp = _get("/api/method/frappe.auth.get_logged_user")
        if resp.status_code != 200:
            raise _SmokeTestError(
                "get_logged_user",
                f"Expected 200, got {resp.status_code}: {resp.text[:300]}",
            )
        tests_run.append("get_logged_user")

        # ── 2. Read the provisioned Company (basic read access check) ───────
        resp = _get(f"/api/resource/Company/{requests.utils.quote(company_name, safe='')}")
        if resp.status_code != 200:
            raise _SmokeTestError(
                "read_company",
                f"Expected 200, got {resp.status_code}: {resp.text[:300]}",
            )
        tests_run.append("read_company")

        # ── 3. Create a test Customer (Selling permissions) ─────────────────
        # Use the Frappe ORM (runs as Administrator inside bench execute) to
        # discover existing Customer Group / Territory rows. Customer Group must
        # be a leaf (is_group == 0); parent nodes such as "All Customer Groups"
        # are invalid on Customer and return HTTP 417 from the REST API.
        customer_group = select_smoke_customer_group(frappe)
        if not customer_group:
            raise _SmokeTestError(
                "resolve_customer_group",
                "No non-group Customer Group available for smoke test",
            )

        territory: str | None = None
        for candidate in ("All Territories", "Default"):
            if frappe.db.exists("Territory", candidate):
                territory = candidate
                break
        if not territory:
            rows = frappe.db.get_all("Territory", pluck="name", limit=1)
            territory = rows[0] if rows else None

        if customer_group and territory:
            resp = _post("/api/resource/Customer", {
                "customer_name": _SMOKE_CUSTOMER,
                "customer_group": customer_group,
                "territory": territory,
            })
            if resp.status_code != 200:
                raise _SmokeTestError(
                    "create_customer",
                    f"Expected 200, got {resp.status_code}: {resp.text[:300]}",
                )
            customer_name = resp.json()["data"]["name"]
            tests_run.append("create_customer")

            # ── 4. Create a draft Sales Invoice (Accounts + Selling) ─────────
            # Discover an item using the ORM.
            item_code: str | None = None
            if frappe.db.exists("Item", "_Test Item"):
                item_code = "_Test Item"
            else:
                items = frappe.db.get_all("Item", filters={"disabled": 0}, fields=["item_code"], limit=1)
                if items:
                    item_code = items[0]["item_code"]

            if item_code:
                resp = _post("/api/resource/Sales Invoice", {
                    "customer": customer_name,
                    "company": company_name,
                    "items": [{"item_code": item_code, "qty": 1, "rate": 100}],
                })
                if resp.status_code != 200:
                    raise _SmokeTestError(
                        "create_invoice",
                        f"Expected 200, got {resp.status_code}: {resp.text[:300]}",
                    )
                invoice_name = resp.json()["data"]["name"]
                tests_run.append("create_invoice")

        tests_run.append("cleanup")

    except _SmokeTestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _SmokeTestError("unexpected", str(exc)) from exc

    finally:
        # Best-effort cleanup — never raise; provisioning must not fail here.
        if invoice_name:
            try:
                _delete(f"/api/resource/Sales Invoice/{invoice_name}")
            except Exception:  # noqa: BLE001
                pass
        if customer_name:
            try:
                _delete(f"/api/resource/Customer/{customer_name}")
            except Exception:  # noqa: BLE001
                pass

    print("ok=true")
    print("smoke_test=passed")
    print(f"tests_run={','.join(tests_run)}")

    return {"ok": True, "smoke_test": "passed", "tests_run": tests_run}
