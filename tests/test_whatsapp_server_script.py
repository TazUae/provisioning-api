"""Regression tests for _create_whatsapp_server_script() — no Frappe bench required.

Protects against silent re-enablement of automatic invoice payment-request
WhatsApp messages, which require explicit trainer action per FitDesk policy.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from provisioning_api.api.fitdesk_setup import _create_whatsapp_server_script


class TestCreateWhatsappServerScript(unittest.TestCase):
    """Regression tests for Server Script provisioning defaults."""

    def _make_frappe(self, script_exists: bool = False) -> MagicMock:
        frappe = MagicMock()
        frappe.db.exists.return_value = script_exists
        frappe.get_doc.return_value = MagicMock()
        return frappe

    def test_script_is_provisioned_disabled(self):
        """FitDesk Invoice Submit Webhook must be created with disabled=1.

        Regression guard: prevents re-introduction of disabled=0, which would
        automatically send a payment-request WhatsApp on every Sales Invoice
        submit.  Payment requests require explicit trainer action.
        """
        frappe = self._make_frappe(script_exists=False)

        _create_whatsapp_server_script(
            frappe,
            control_plane_webhook_url="https://cp.example.com/webhooks/invoice-submitted",
            control_plane_webhook_secret="test-secret",
            tenant_slug="test-tenant",
        )

        frappe.get_doc.assert_called_once()
        doc_dict = frappe.get_doc.call_args[0][0]
        self.assertEqual(
            doc_dict["disabled"],
            1,
            "Server Script must be provisioned disabled=1; "
            "payment requests require explicit trainer action",
        )

    def test_returns_script_name_on_creation(self):
        """Successful creation returns the script name."""
        frappe = self._make_frappe(script_exists=False)

        result = _create_whatsapp_server_script(
            frappe,
            control_plane_webhook_url="https://cp.example.com/webhooks/invoice-submitted",
            control_plane_webhook_secret="test-secret",
            tenant_slug="test-tenant",
        )

        self.assertEqual(result, {"server_script": "FitDesk Invoice Submit Webhook"})

    def test_skips_when_script_already_exists(self):
        """Idempotency: returns skipped=True without touching the existing script."""
        frappe = self._make_frappe(script_exists=True)

        result = _create_whatsapp_server_script(
            frappe,
            control_plane_webhook_url="https://cp.example.com/webhooks/invoice-submitted",
            control_plane_webhook_secret="test-secret",
            tenant_slug="test-tenant",
        )

        self.assertEqual(result, {"skipped": True})
        frappe.get_doc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
