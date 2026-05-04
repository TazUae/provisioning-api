"""Unit tests for smoke test Customer Group selection (no Frappe bench required)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from provisioning_api.api.smoke_test import select_smoke_customer_group


class TestSelectSmokeCustomerGroup(unittest.TestCase):
    def _frappe_with_db(self, db: MagicMock) -> MagicMock:
        frappe = MagicMock()
        frappe.db = db
        return frappe

    def test_prefers_individual_when_all_customer_groups_is_group(self):
        """All Customer Groups is_group=1 and Individual is_group=0 -> Individual."""

        def exists(doctype, name):
            return name in ("All Customer Groups", "Individual")

        def get_value(doctype, name, field):
            if name == "All Customer Groups":
                return 1
            if name == "Individual":
                return 0
            return None

        db = MagicMock()
        db.exists.side_effect = exists
        db.get_value.side_effect = get_value
        db.get_all.return_value = []

        chosen = select_smoke_customer_group(self._frappe_with_db(db))
        self.assertEqual(chosen, "Individual")

    def test_skips_commercial_when_it_is_group_node(self):
        """Commercial exists but is_group=1 -> skips to Default when Default is leaf."""

        def exists(doctype, name):
            return name in ("Commercial", "Default")

        def get_value(doctype, name, field):
            if name == "Commercial":
                return 1
            if name == "Default":
                return 0
            return None

        db = MagicMock()
        db.exists.side_effect = exists
        db.get_value.side_effect = get_value
        db.get_all.return_value = []

        chosen = select_smoke_customer_group(self._frappe_with_db(db))
        self.assertEqual(chosen, "Default")

    def test_fallback_get_all_returns_leaf(self):
        """When preferred names missing or not leaf, first is_group=0 from get_all wins."""

        def exists(doctype, name):
            return False

        db = MagicMock()
        db.exists.side_effect = exists
        db.get_all.return_value = ["Leaf Region"]

        chosen = select_smoke_customer_group(self._frappe_with_db(db))
        self.assertEqual(chosen, "Leaf Region")
        db.get_all.assert_called_once_with(
            "Customer Group",
            filters={"is_group": 0},
            pluck="name",
            limit=1,
        )

    def test_returns_none_when_no_leaf_groups(self):
        db = MagicMock()
        db.exists.return_value = False
        db.get_all.return_value = []

        chosen = select_smoke_customer_group(self._frappe_with_db(db))
        self.assertIsNone(chosen)


if __name__ == "__main__":
    unittest.main()
