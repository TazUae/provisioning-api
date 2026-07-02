# Copyright (c) 2026, TazUae and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FDSession(Document):
    def validate(self):
        self._validate_occurrence_uniqueness()

    def _validate_occurrence_uniqueness(self):
        """Guard against duplicate (series_id, occurrence_key) pairs."""
        if not self.series_id or not self.occurrence_key:
            return
        existing = frappe.db.exists(
            "FD Session",
            {
                "series_id": self.series_id,
                "occurrence_key": self.occurrence_key,
                "name": ("!=", self.name or ""),
            },
        )
        if existing:
            frappe.throw(
                f"Occurrence '{self.occurrence_key}' already exists in series '{self.series_id}'.",
                frappe.DuplicateEntryError,
            )
