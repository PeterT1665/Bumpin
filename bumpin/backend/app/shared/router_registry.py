"""Routers from shared/ and vendors/ that main.py includes.

Created by Backend A in the skeleton commit. Backend B owns this file now:
append each new APIRouter to ROUTERS.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.shared.notifications import router as notifications_router

from backend.app.shared.outbox import router as outbox_router

from backend.app.shared.tickets import router as tickets_router

from backend.app.shared.inbox import router as inbox_router

ROUTERS: list[APIRouter] = [notifications_router, outbox_router, tickets_router, inbox_router]
