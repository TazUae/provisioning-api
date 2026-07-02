"""Smoke tests for provisioning_api.api.fitdesk_setup.

Full integration tests (with live Frappe bench) are in the bench-agent
integration suite. These tests verify:
- Module imports and expected functions exist
- Parameter validation (catches errors before touching Frappe)
- Account lookup and Mode of Payment upsert logic (mocked Frappe only)
"""

import unittest
from unittest.mock import MagicMock, Mock, patch


class TestFitdeskSetupModule(unittest.TestCase):
    """Test imports and function exposure."""

    def test_module_imports(self):
        from provisioning_api.api import fitdesk_setup

        self.assertTrue(hasattr(fitdesk_setup, "setup_fitdesk_schema"))
        self.assertTrue(callable(fitdesk_setup.setup_fitdesk_schema))

    def test_create_mode_of_payment_function_exists(self):
        from provisioning_api.api.fitdesk_setup import _create_mode_of_payment

        self.assertTrue(callable(_create_mode_of_payment))

    def test_upsert_mode_of_payment_function_exists(self):
        from provisioning_api.api.fitdesk_setup import _upsert_mode_of_payment

        self.assertTrue(callable(_upsert_mode_of_payment))

    def test_get_account_for_company_function_exists(self):
        from provisioning_api.api.fitdesk_setup import _get_account_for_company

        self.assertTrue(callable(_get_account_for_company))


class TestAccountLookup(unittest.TestCase):
    """Test _get_account_for_company with mocked Frappe."""

    def test_find_preferred_account_type(self):
        """Should return account when preferred type exists."""
        from provisioning_api.api.fitdesk_setup import _get_account_for_company

        frappe = MagicMock()
        frappe.db.get_value.return_value = "Cash-Account-001"

        result = _get_account_for_company(frappe, "Test Company", "Cash")

        self.assertEqual(result, "Cash-Account-001")
        frappe.db.get_value.assert_called_once()

    def test_fall_back_to_alternate_account_type(self):
        """Should fall back to alternate type if preferred not found."""
        from provisioning_api.api.fitdesk_setup import _get_account_for_company

        frappe = MagicMock()
        # First call returns None (Cash not found), second call returns Bank
        frappe.db.get_value.side_effect = [None, "Bank-Account-001"]

        result = _get_account_for_company(
            frappe, "Test Company", "Cash", fallback_account_type="Bank"
        )

        self.assertEqual(result, "Bank-Account-001")
        self.assertEqual(frappe.db.get_value.call_count, 2)

    def test_return_none_if_no_account_found(self):
        """Should return None if neither preferred nor fallback found."""
        from provisioning_api.api.fitdesk_setup import _get_account_for_company

        frappe = MagicMock()
        frappe.db.get_value.side_effect = [None, None]

        result = _get_account_for_company(
            frappe, "Test Company", "Cash", fallback_account_type="Bank"
        )

        self.assertIsNone(result)


class TestModeOfPaymentUpsert(unittest.TestCase):
    """Test _upsert_mode_of_payment idempotency with mocked Frappe."""

    def test_raises_if_account_name_is_none(self):
        """Should raise ValueError if account_name is None."""
        from provisioning_api.api.fitdesk_setup import _upsert_mode_of_payment

        frappe = MagicMock()

        with self.assertRaises(ValueError) as ctx:
            _upsert_mode_of_payment(frappe, "Cash", "Cash", "Test Company", None)

        self.assertIn("no suitable account", str(ctx.exception))
        self.assertIn("Cash", str(ctx.exception))

    def test_create_new_mode_of_payment(self):
        """Should create new Mode of Payment if it doesn't exist."""
        from provisioning_api.api.fitdesk_setup import _upsert_mode_of_payment

        frappe = MagicMock()
        frappe.db.exists.return_value = False

        mock_doc = MagicMock()
        frappe.get_doc.return_value = mock_doc

        result = _upsert_mode_of_payment(
            frappe, "Cash", "Cash", "Test Company", "Cash-Account-001"
        )

        self.assertEqual(result["created"], "Cash")
        self.assertEqual(result["account"], "Cash-Account-001")
        frappe.get_doc.assert_called_once()
        mock_doc.insert.assert_called_once()
        frappe.db.commit.assert_called_once()

    def test_skip_if_company_already_configured(self):
        """Should skip if Mode exists and company is already configured."""
        from provisioning_api.api.fitdesk_setup import _upsert_mode_of_payment

        frappe = MagicMock()
        frappe.db.exists.return_value = True

        mock_account = MagicMock()
        mock_account.company = "Test Company"
        mock_doc = MagicMock()
        mock_doc.accounts = [mock_account]
        frappe.get_doc.return_value = mock_doc

        result = _upsert_mode_of_payment(
            frappe, "Cash", "Cash", "Test Company", "Cash-Account-001"
        )

        self.assertEqual(result["skipped"], "Cash")
        mock_doc.save.assert_not_called()
        frappe.db.commit.assert_not_called()

    def test_upsert_if_company_not_configured(self):
        """Should add company row if Mode exists but company not configured."""
        from provisioning_api.api.fitdesk_setup import _upsert_mode_of_payment

        frappe = MagicMock()
        frappe.db.exists.return_value = True

        # Simulate existing account for different company
        mock_account = MagicMock()
        mock_account.company = "Other Company"
        mock_doc = MagicMock()
        mock_doc.accounts = [mock_account]
        frappe.get_doc.return_value = mock_doc

        result = _upsert_mode_of_payment(
            frappe, "Cash", "Cash", "Test Company", "Cash-Account-001"
        )

        self.assertEqual(result["upserted"], "Cash")
        self.assertEqual(result["account"], "Cash-Account-001")
        mock_doc.append.assert_called_once()
        mock_doc.save.assert_called_once()
        frappe.db.commit.assert_called_once()


class TestCreateModeOfPayment(unittest.TestCase):
    """Test _create_mode_of_payment (full orchestration)."""

    def test_creates_all_three_modes(self):
        """Should create Cash, Bank Transfer, and Whish Money."""
        from provisioning_api.api.fitdesk_setup import _create_mode_of_payment

        frappe = MagicMock()

        # Mock account lookups: all successful (no fallbacks for Cash/Bank)
        frappe.db.get_value.side_effect = [
            "Cash-Account",      # Cash required (Cash type)
            "Bank-Account",      # Bank Transfer required (Bank type)
            "Bank-Account",      # Whish Money preferred (Bank type)
        ]

        # Mock Mode of Payment creation
        frappe.db.exists.return_value = False
        mock_doc = MagicMock()
        frappe.get_doc.return_value = mock_doc

        result = _create_mode_of_payment(frappe, "Test Company", "TC")

        self.assertIn("modes", result)
        self.assertIn("Cash", result["modes"])
        self.assertIn("Bank Transfer", result["modes"])
        self.assertIn("Whish Money", result["modes"])

    def test_raises_if_no_cash_account(self):
        """Should raise clear error if no Cash account available (no fallback)."""
        from provisioning_api.api.fitdesk_setup import _create_mode_of_payment

        frappe = MagicMock()
        frappe.db.get_value.return_value = None  # No Cash account found

        with self.assertRaises(ValueError) as ctx:
            _create_mode_of_payment(frappe, "Test Company", "TC")

        self.assertIn("Cannot configure Cash", str(ctx.exception))
        self.assertIn("no Cash account", str(ctx.exception))

    def test_raises_if_no_bank_account(self):
        """Should raise clear error if no Bank account available (no fallback)."""
        from provisioning_api.api.fitdesk_setup import _create_mode_of_payment

        frappe = MagicMock()
        frappe.db.get_value.side_effect = [
            "Cash-Account",  # Cash succeeds
            None,            # Bank Transfer fails (no Bank account)
        ]

        with self.assertRaises(ValueError) as ctx:
            _create_mode_of_payment(frappe, "Test Company", "TC")

        self.assertIn("Cannot configure Bank Transfer", str(ctx.exception))
        self.assertIn("no Bank account", str(ctx.exception))

    def test_prefers_cash_type_for_cash_mode(self):
        """Cash mode should prefer Cash account over Bank."""
        from provisioning_api.api.fitdesk_setup import (
            _get_account_for_company,
        )

        frappe = MagicMock()
        frappe.db.get_value.return_value = "Cash-Account-001"

        result = _get_account_for_company(frappe, "Test Company", "Cash", "Bank")

        # Should query for Cash type first
        call_args_list = frappe.db.get_value.call_args_list
        first_call = call_args_list[0]
        self.assertIn("Cash", str(first_call))


class TestVerifyFitdeskSchema(unittest.TestCase):
    """Test verify_fitdesk_schema — core ok gates and advisory payment mode checks."""

    def test_ok_true_when_core_schema_complete(self):
        """verify_fitdesk_schema should return ok=True when core billing schema is present."""
        from provisioning_api.api.fitdesk_setup import verify_fitdesk_schema

        frappe = MagicMock()
        # Two count calls: total custom fields (15), core billing fields (4)
        frappe.db.count.side_effect = [15, 4]
        frappe.db.exists.side_effect = [
            True,  # Item TRAINING-SESSION
            True,  # Customer Group Individual
            True,  # Print Format FitDesk Invoice
            True,  # Price List Standard Selling
            True,  # Mode of Payment: Cash
            True,  # Mode of Payment: Bank Transfer
            True,  # Mode of Payment: Whish Money
            True,  # Server Script
        ]

        with patch.dict("sys.modules", {"frappe": frappe}):
            result = verify_fitdesk_schema("Test Company")

        self.assertEqual(result["ok"], True)
        self.assertIn("mode_of_payment_cash", result["checks"])
        self.assertIn("mode_of_payment_bank_transfer", result["checks"])
        self.assertIn("mode_of_payment_whish", result["checks"])
        self.assertTrue(result["checks"]["mode_of_payment_cash"])
        self.assertTrue(result["checks"]["mode_of_payment_bank_transfer"])
        self.assertTrue(result["checks"]["mode_of_payment_whish"])

    def test_payment_modes_are_advisory_not_blocking(self):
        """Missing payment modes should not make ok False — they are advisory only."""
        from provisioning_api.api.fitdesk_setup import verify_fitdesk_schema

        frappe = MagicMock()
        frappe.db.count.side_effect = [15, 4]  # core schema fully present
        frappe.db.exists.side_effect = [
            True,   # Item TRAINING-SESSION
            True,   # Customer Group Individual
            True,   # Print Format FitDesk Invoice
            True,   # Price List Standard Selling
            True,   # Cash present
            False,  # Bank Transfer MISSING
            False,  # Whish Money MISSING
            False,  # Server Script absent
        ]

        with patch.dict("sys.modules", {"frappe": frappe}):
            result = verify_fitdesk_schema("Test Company")

        # Missing payment modes must not affect ok
        self.assertEqual(result["ok"], True)
        self.assertFalse(result["checks"]["mode_of_payment_bank_transfer"])
        self.assertFalse(result["checks"]["mode_of_payment_whish"])

    def test_missing_required_billing_field_makes_ok_false(self):
        """If a required billing custom field is absent, ok should be False."""
        from provisioning_api.api.fitdesk_setup import verify_fitdesk_schema

        frappe = MagicMock()
        # core_billing_fields = 3 (e.g. custom_fd_session absent)
        frappe.db.count.side_effect = [14, 3]
        frappe.db.exists.side_effect = [
            True,  # Item TRAINING-SESSION
            True,  # Customer Group Individual
            True,  # Print Format FitDesk Invoice
            True,  # Price List Standard Selling
            True,  # Cash
            True,  # Bank Transfer
            True,  # Whish Money
            False, # Server Script
        ]

        with patch.dict("sys.modules", {"frappe": frappe}):
            result = verify_fitdesk_schema("Test Company")

        self.assertEqual(result["ok"], False)
        self.assertEqual(result["checks"]["core_billing_fields"], 3)

    def test_missing_standard_selling_price_list_makes_ok_false(self):
        """Missing Standard Selling price list makes ok False — invoice submit would fail."""
        from provisioning_api.api.fitdesk_setup import verify_fitdesk_schema

        frappe = MagicMock()
        frappe.db.count.side_effect = [15, 4]  # all custom fields present
        frappe.db.exists.side_effect = [
            True,  # Item TRAINING-SESSION
            True,  # Customer Group Individual
            True,  # Print Format FitDesk Invoice
            False, # Price List Standard Selling MISSING
            True,  # Cash
            True,  # Bank Transfer
            True,  # Whish Money
            True,  # Server Script
        ]

        with patch.dict("sys.modules", {"frappe": frappe}):
            result = verify_fitdesk_schema("Test Company")

        self.assertEqual(result["ok"], False)
        self.assertFalse(result["checks"]["price_list_standard_selling"])

    def test_payment_method_checks_visible_in_checks(self):
        """Payment method check results must appear in checks even when all modes absent."""
        from provisioning_api.api.fitdesk_setup import verify_fitdesk_schema

        frappe = MagicMock()
        frappe.db.count.side_effect = [15, 4]
        frappe.db.exists.side_effect = [
            True,  # Item
            True,  # Customer Group
            True,  # Print Format
            True,  # Price List Standard Selling
            False, # Cash MISSING
            False, # Bank Transfer MISSING
            False, # Whish Money MISSING
            False, # Server Script
        ]

        with patch.dict("sys.modules", {"frappe": frappe}):
            result = verify_fitdesk_schema("Test Company")

        # ok is True — core schema is present; payment modes are advisory
        self.assertEqual(result["ok"], True)
        self.assertIn("mode_of_payment_cash", result["checks"])
        self.assertIn("mode_of_payment_bank_transfer", result["checks"])
        self.assertIn("mode_of_payment_whish", result["checks"])
        self.assertFalse(result["checks"]["mode_of_payment_cash"])
        self.assertFalse(result["checks"]["mode_of_payment_bank_transfer"])
        self.assertFalse(result["checks"]["mode_of_payment_whish"])


if __name__ == "__main__":
    unittest.main()
