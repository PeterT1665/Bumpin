"""GET /vendors for the laptop app."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app import db

router = APIRouter(tags=["vendors"])

_LIST_SQL = """
SELECT v.*,
  (SELECT COUNT(*) FROM documents d WHERE d.owner_type = 'vendor' AND d.owner_id = v.id) AS document_count,
  (SELECT MIN(d.expiry_date) FROM documents d WHERE d.owner_type = 'vendor' AND d.owner_id = v.id
     AND d.expiry_date IS NOT NULL) AS earliest_expiry,
  (SELECT t.id FROM tickets t WHERE t.owner_type = 'vendor' AND t.owner_id = v.id
     ORDER BY t.updated_at DESC, t.id DESC LIMIT 1) AS latest_ticket_id,
  (SELECT t.status FROM tickets t WHERE t.owner_type = 'vendor' AND t.owner_id = v.id
     ORDER BY t.updated_at DESC, t.id DESC LIMIT 1) AS latest_ticket_status
FROM vendors v
"""


@router.get("/vendors")
def list_vendors(type: str | None = None, status: str | None = None) -> list[dict]:
    sql, args = _LIST_SQL + " WHERE 1=1", []
    if type:
        sql += " AND v.type = ?"
        args.append(type)
    if status:
        sql += " AND v.status = ?"
        args.append(status)
    with db.get_conn() as conn:
        out = db.rows(conn.execute(sql + " ORDER BY v.name", args))
    for v in out:
        v["uses_gas"] = bool(v["uses_gas"])
    return out


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: int) -> dict:
    with db.get_conn() as conn:
        v = db.row(conn.execute(_LIST_SQL + " WHERE v.id = ?", (vendor_id,)))
        if v is None:
            raise HTTPException(404, f"vendor {vendor_id} not found")
        v["uses_gas"] = bool(v["uses_gas"])
        v["documents"] = db.rows(conn.execute(
            """SELECT id, kind, filename, expiry_date, issuer, received_at FROM documents
               WHERE owner_type = 'vendor' AND owner_id = ? ORDER BY id""", (vendor_id,)))
    return v
