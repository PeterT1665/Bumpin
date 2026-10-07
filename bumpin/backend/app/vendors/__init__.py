"""Vendor side (Backend B). Entry points for the inbox pipeline:

    from backend.app import vendors
    vendors.create_vendor_ticket(email_id, classification)          # label vendor_doc
    vendors.create_vendor_change_ticket(email_id, classification)   # help_or_change from a vendor

Importing this package registers the vendor_eligibility ticket handler.
"""

from backend.app.vendors.docs import VendorDocFacts, extract_vendor_doc
from backend.app.vendors.eligibility import check_eligibility
from backend.app.vendors.tickets import (
    VendorBlocked,
    create_vendor_change_ticket,
    create_vendor_ticket,
    recommend_rejection,
)

__all__ = [
    "VendorBlocked", "VendorDocFacts", "check_eligibility", "create_vendor_change_ticket",
    "create_vendor_ticket", "extract_vendor_doc", "recommend_rejection",
]
