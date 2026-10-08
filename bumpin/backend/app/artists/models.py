from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RiderItem(BaseModel):
    id: int | None = None
    artist_id: int | None = None
    doc_id: int | None = None
    name: str
    raw_text: str
    quote: str
    page: int = 1
    category: Literal["technical", "hospitality"]
    quantity: int = 1
    inventory_item_id: int | None = None
    unit_cost: float | None = None
    match_confidence: float = 0.0
    match_label: str | None = None  # canonical inventory name or hospitality label


class Finding(BaseModel):
    kind: str
    severity: Literal["conflict", "warning", "info"]
    message: str
    suggestion: str = ""
    doc_id: int | None = None
    quote: str | None = None
    page: int | None = None
    facts: dict = {}


class ProposedAction(BaseModel):
    index: int
    kind: Literal["move_set", "notify"]
    title: str
    detail: str
    to_addr: str | None = None
    artist_id: int | None = None
    new_start: str | None = None
    new_end: str | None = None
    status: Literal["proposed", "approved"] = "proposed"
    approved_by: str | None = None
    outbox_id: int | None = None


class RunsheetRow(BaseModel):
    day: str
    start: str
    end: str
    area: str
    who: str
    kind: Literal["set", "load_in"]
    status: str
    contact: str | None = None
    #: Which artist this row IS, so the screen can offer to take it off the sheet again.
    #: None on a vendor load-in, which is not a row the run sheet owns — the load-in
    #: window lives on the vendor and is moved by approving that vendor's ticket.
    artist_id: int | None = None
