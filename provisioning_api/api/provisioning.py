import subprocess
import re


def create_site(site_name: str):
    if not site_name:
        return {"ok": False, "error": "site_name required"}

    if not re.match(r"^[a-z0-9-]+$", site_name):
        return {"ok": False, "error": "invalid site_name"}

    try:
        subprocess.run(
            [
                "bench",
                "new-site",
                site_name,
                "--admin-password",
                "admin",
                "--db-type",
                "mariadb",
                "--install-app",
                "erpnext",
            ],
            check=True
        )

        return {
            "ok": True,
            "data": {
                "site": site_name
            }
        }

    except subprocess.CalledProcessError as e:
        return {
            "ok": False,
            "error": str(e)
        }
