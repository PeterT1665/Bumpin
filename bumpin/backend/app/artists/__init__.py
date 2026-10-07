"""Artist side (Backend A). Entry points for the inbox pipeline:

    from backend.app import artists
    artists.create_rider_ticket(email_id, classification)
    artists.create_help_ticket(email_id, classification)

Importing this package registers the rider_needs and help ticket handlers.
"""

from backend.app.artists.ripple import create_help_ticket, ripple_for_change
from backend.app.artists.tickets import RiderBlocked, create_rider_ticket

__all__ = ["create_rider_ticket", "create_help_ticket", "ripple_for_change", "RiderBlocked"]
