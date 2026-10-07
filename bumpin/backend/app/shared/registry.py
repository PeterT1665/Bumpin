"""Ticket handler registry. Handlers register by ticket type and the generic
tickets router dispatches to them (contract section 6)."""

from __future__ import annotations

from typing import Protocol


class TicketHandler(Protocol):
    def approve(self, ticket_id: int, actor: str, payload: dict | None) -> None: ...
    def reject(self, ticket_id: int, actor: str, reason: str) -> None: ...
    def resolve_finding(self, ticket_id: int, finding_id: int, actor: str) -> None: ...
    def ignore_finding(self, ticket_id: int, finding_id: int, actor: str) -> None: ...
    def approve_action(self, ticket_id: int, index: int, actor: str) -> None: ...
    def edit_action(self, ticket_id: int, index: int, actor: str, edits: dict) -> None: ...
    def deny_action(self, ticket_id: int, index: int, actor: str) -> None: ...


_HANDLERS: dict[str, TicketHandler] = {}


def register_handler(ticket_type: str, handler: TicketHandler) -> None:
    _HANDLERS[ticket_type] = handler


def get_handler(ticket_type: str) -> TicketHandler:
    """Raises KeyError (mapped to 404 by the router) when no handler is registered."""
    try:
        return _HANDLERS[ticket_type]
    except KeyError:
        raise KeyError(f"no handler registered for ticket type {ticket_type!r}") from None
