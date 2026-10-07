"""Shared FastAPI dependencies. Any router can import these."""

from __future__ import annotations

from typing import Literal

from fastapi import Header, HTTPException

User = Literal["ravi", "jess"]
USERS = ("ravi", "jess")


def current_user(x_user: str | None = Header(default=None)) -> str:
    """Acting user from the X-User header. Defaults to ravi when missing."""
    user = (x_user or "ravi").strip().lower()
    if user not in USERS:
        raise HTTPException(status_code=400, detail=f"X-User must be one of {USERS}")
    return user
