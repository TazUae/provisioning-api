"""Smoke tests for provisioning_api.api.user.

Full behavior requires a live Frappe bench (frappe.get_doc, frappe.db,
User doctype); those tests live in the bench-agent integration suite.
Here we only guarantee the module imports and exposes the expected
contract for bench-agent to call via `bench execute`.
"""

import unittest


class TestUserApiModule(unittest.TestCase):
    def test_module_imports(self):
        from provisioning_api.api import user

        self.assertTrue(hasattr(user, "create_api_user"))
        self.assertTrue(callable(user.create_api_user))

    def test_create_api_user_rejects_empty_username(self):
        from provisioning_api.api.user import create_api_user

        # Raises before touching frappe, so safe to exercise without a bench.
        with self.assertRaises(ValueError):
            create_api_user("")
        with self.assertRaises(ValueError):
            create_api_user("   ")
        with self.assertRaises(ValueError):
            create_api_user(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
