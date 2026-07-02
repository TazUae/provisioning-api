"""User / API key operations invoked by bench-agent via `bench execute`.

Why this lives here (not in bench-agent directly):
    - Creating a User and generating api_key/api_secret requires the Frappe
      ORM, which is only available inside a live Frappe runtime.
    - bench-agent runs outside the Frappe request cycle; it shells out to
      `bench --site <site> execute provisioning_api.api.user.create_api_user`
      which spins up a Frappe environment for us.

Contract with bench-agent:
    create_api_user prints TWO lines to stdout on success, parsed by
    `axis_bench_agent.bench._parse_api_credentials`:

        api_key=<token>
        api_secret=<token>

    setup_roles prints TWO lines to stdout on success, parsed by
    `axis_bench_agent.bench._parse_roles_result`:

        ok=true
        roles_assigned=<int>

    Any other stdout is ignored. On failure the function raises, which
    makes `bench execute` exit non-zero and bench-agent classifies it as
    a BenchCommandError.
"""

from __future__ import annotations

PROVISIONING_ROLES = [
    "System Manager",
    "Sales Manager",
    "Sales User",
    "Sales Master Manager",
    "Accounts Manager",
    "Accounts User",
    "Stock Manager",
    "Stock User",
    "Purchase Manager",
    "Purchase User",
    "HR Manager",
    "HR User",
    "Projects Manager",
    "Project User",
    "Manufacturing Manager",
    "Manufacturing User",
    "Healthcare Administrator",
    "Quality Manager",
    "Loans Manager",
    "Asset Manager",
]

# Manager/admin roles to assign to the site's Administrator user.
# Excludes *User roles — Administrator already has broader access via System Manager.
ADMIN_ROLES = [r for r in PROVISIONING_ROLES if not r.endswith(" User")]


def create_api_user(username: str) -> dict:
    """Create (or reuse) a provisioning API user and return its credentials.

    Idempotency:
        - If a user with this email already exists, we reuse it.
        - If the existing user already has api_key/api_secret we rotate them
          (bench-agent is expected to be called from a retry path, and
          returning stale credentials would make the retry a no-op).
    """
    if not username or not isinstance(username, str):
        raise ValueError("username is required")
    username = username.strip().lower()
    if not username:
        raise ValueError("username is required")

    import frappe  # imported lazily — only available under `bench execute`

    email = f"{username}@axis.local"

    user = _get_or_create_user(frappe, email=email, username=username)
    api_key, api_secret = _rotate_api_credentials(frappe, user)

    frappe.db.commit()

    # bench-agent parses these two lines out of stdout.
    print(f"api_key={api_key}")
    print(f"api_secret={api_secret}")

    return {
        "ok": True,
        "user": email,
        "api_key": api_key,
        "api_secret": api_secret,
    }


def setup_roles(username: str) -> dict:
    """Sync the full PROVISIONING_ROLES set onto the API user and Administrator.

    Idempotent: safe to re-run. Uses diff-and-patch so existing extra roles
    granted manually are removed and missing roles are added.

    Also grants all ADMIN_ROLES to the site's built-in Administrator user so
    that human admins can access all ERPNext modules via the UI.

    stdout contract (for bench-agent parsing):
        ok=true
        roles_assigned=<int>   # number of roles added to the API user
    """
    if not username or not isinstance(username, str):
        raise ValueError("username is required")
    username = username.strip().lower()
    if not username:
        raise ValueError("username is required")

    import frappe  # imported lazily — only available under `bench execute`

    email = f"{username}@axis.local"
    user = _get_or_create_user(frappe, email=email, username=username)

    # Only operate on roles that actually exist on this site.
    existing_roles = _filter_existing_roles(frappe, PROVISIONING_ROLES)
    roles_assigned = _sync_roles(frappe, user, existing_roles)

    # Sync manager roles onto the built-in Administrator user.
    admin_existing = _filter_existing_roles(frappe, ADMIN_ROLES)
    if frappe.db.exists("User", "Administrator"):
        admin_user = frappe.get_doc("User", "Administrator")
        _sync_roles(frappe, admin_user, admin_existing)

    frappe.db.commit()

    print("ok=true")
    print(f"roles_assigned={roles_assigned}")

    return {"ok": True, "user": email, "roles_assigned": roles_assigned}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_user(frappe, *, email: str, username: str):
    if frappe.db.exists("User", email):
        return frappe.get_doc("User", email)

    existing_roles = _filter_existing_roles(frappe, PROVISIONING_ROLES)
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": username,
            "send_welcome_email": 0,
            "enabled": 1,
            "user_type": "System User",
            "roles": [{"role": r} for r in existing_roles],
        }
    )
    user.insert(ignore_permissions=True)
    return user


def _filter_existing_roles(frappe, roles: list) -> list:
    """Return only the role names that have a Role document on this site."""
    existing = {r["name"] for r in frappe.db.get_all("Role", fields=["name"])}
    return [r for r in roles if r in existing]


def _sync_roles(frappe, user, target_roles: list) -> int:
    """Diff-and-patch user.roles to match target_roles.

    Returns the number of roles that were added (not the total count).
    Saves and commits if there are any changes.
    """
    target_set = set(target_roles)
    current_roles = {r.role for r in user.roles}

    # Roles to remove (in current but not in target)
    user.roles = [r for r in user.roles if r.role in target_set]

    # Roles to add (in target but not in current)
    added = 0
    for role in target_roles:
        if role not in current_roles:
            user.append("roles", {"role": role})
            added += 1

    if added or (current_roles != target_set):
        user.save(ignore_permissions=True)

    return added


def _rotate_api_credentials(frappe, user) -> tuple:
    # User.api_key is a Data field, User.api_secret is a Password field.
    # Frappe's doc.save() handles encryption of Password fields automatically.
    api_key = frappe.generate_hash(length=15)
    api_secret = frappe.generate_hash(length=15)
    user.api_key = api_key
    user.api_secret = api_secret
    user.save(ignore_permissions=True)
    return api_key, api_secret
