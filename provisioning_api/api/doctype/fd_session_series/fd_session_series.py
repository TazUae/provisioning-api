# Copyright (c) 2026, TazUae and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FDSessionSeries(Document):
    def validate(self):
        self._validate_pattern()

    def _validate_pattern(self):
        if not self.pattern:
            frappe.throw("Pattern is required.", frappe.ValidationError)
        try:
            frappe.parse_json(self.pattern)
        except Exception:
            frappe.throw("Pattern must be valid JSON.", frappe.ValidationError)
