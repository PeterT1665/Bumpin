"""Rider checks in plain code: shortages, shared-pool double bookings, hospitality budget.

The LLM only rewords the message and suggestion after the numbers are decided here.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from backend.app import db
from backend.app.artists import ai
from backend.app.artists.models import Finding
from backend.app.artists.riders import _alias_match
from backend.app.shared.rules import load_rules


def _artist(conn, artist_id: int) -> dict:
    a = db.row(conn.execute(
        """SELECT a.*, s.name AS stage_name FROM artists a
           LEFT JOIN stages s ON s.id = a.stage_id WHERE a.id = ?""",
        (artist_id,),
    ))
    if a is None:
        raise KeyError(f"artist {artist_id} not found")
    return a


def _items(conn, artist_id: int, category: str) -> list[dict]:
    return db.rows(conn.execute(
        "SELECT * FROM rider_items WHERE artist_id = ? AND category = ? ORDER BY id",
        (artist_id, category),
    ))


def _hhmm(ts: str | None) -> str:
    return ts[11:16] if ts else "?"


def _overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return a_start < b_end and b_start < a_end


def check_shortage(artist_id: int) -> list[Finding]:
    """Requested quantity above what the artist's stage (or the shared pool) owns."""
    findings: list[Finding] = []
    with db.get_conn() as conn:
        artist = _artist(conn, artist_id)
        items = _items(conn, artist_id, "technical")
        inventory = {i["id"]: i for i in db.rows(conn.execute("SELECT * FROM inventory_items"))}

    requested: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        if it["inventory_item_id"]:
            requested[it["inventory_item_id"]].append(it)
            continue
        # Not on this stage at all: if another stage owns it, the stage has 0.
        elsewhere = _alias_match(it["raw_text"], list(inventory.values()))
        if elsewhere:
            findings.append(_shortage(artist, elsewhere["canonical_name"], it["quantity"], 0, it))
        else:
            findings.append(Finding(
                kind="low_confidence", severity="warning",
                message=f"Could not match \"{it['raw_text']}\" to any {artist['stage_name']} equipment.",
                suggestion="Check this line by hand and confirm what the artist means.",
                doc_id=it["doc_id"], quote=it["quote"], page=it["page"],
            ))

    for item_id, lines in requested.items():
        inv = inventory[item_id]
        qty = sum(line["quantity"] for line in lines)
        if qty > inv["quantity_total"]:
            findings.append(_shortage(artist, inv["canonical_name"], qty, inv["quantity_total"], lines[0],
                                      shared=inv["stage_id"] is None))
    return findings


def _shortage(artist: dict, name: str, wanted: int, have: int, line: dict, shared: bool = False) -> Finding:
    where = "the shared pool" if shared else artist["stage_name"]
    gap = wanted - have
    facts = {"artist": artist["name"], "item": name, "requested": wanted, "available": have, "where": where}
    message = f"Rider asks for {wanted}x {name}, {where} has {have}."
    if have:
        suggestion = f"Ask {artist['manager_name'] or 'the manager'} to accept {have}, or arrange an external rental for {gap}."
    else:
        suggestion = f"Ask {artist['manager_name'] or 'the manager'} to bring their own or arrange an external rental for {gap}."
    message, suggestion = ai.explain("shortage", facts, message, suggestion)
    return Finding(kind="shortage", severity="conflict", message=message, suggestion=suggestion,
                   doc_id=line["doc_id"], quote=line["quote"], page=line["page"], facts=facts)


def check_double_booking(artist_id: int) -> list[Finding]:
    """Shared-pool items wanted by more artists than exist during overlapping set windows."""
    findings: list[Finding] = []
    with db.get_conn() as conn:
        artist = _artist(conn, artist_id)
        mine = db.rows(conn.execute(
            """SELECT r.*, i.canonical_name, i.quantity_total FROM rider_items r
               JOIN inventory_items i ON i.id = r.inventory_item_id
               WHERE r.artist_id = ? AND i.stage_id IS NULL""",
            (artist_id,),
        ))
        for line in mine:
            # Other artists who still want the item: rider not rejected.
            others = db.rows(conn.execute(
                """SELECT a.id, a.name, a.set_start, a.set_end, s.name AS stage_name, SUM(r.quantity) AS qty
                   FROM rider_items r
                   JOIN artists a ON a.id = r.artist_id
                   LEFT JOIN stages s ON s.id = a.stage_id
                   WHERE r.inventory_item_id = ? AND r.artist_id != ?
                     AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.type = 'rider_needs'
                                     AND t.owner_type = 'artist' AND t.owner_id = a.id AND t.status = 'rejected')
                   GROUP BY a.id""",
                (line["inventory_item_id"], artist_id),
            ))
            clashes = [o for o in others
                       if _overlaps(artist["set_start"], artist["set_end"], o["set_start"], o["set_end"])]
            if not clashes:
                continue
            total = line["quantity"] + sum(o["qty"] for o in clashes)
            if total <= line["quantity_total"]:
                continue
            other = clashes[0]
            facts = {
                "item": line["canonical_name"], "available": line["quantity_total"],
                "artist": artist["name"], "artist_set": f"{_hhmm(artist['set_start'])} to {_hhmm(artist['set_end'])}",
                "other_artist": other["name"], "other_stage": other["stage_name"],
                "other_set": f"{_hhmm(other['set_start'])} to {_hhmm(other['set_end'])}",
            }
            message = (
                f"{artist['name']} ({facts['artist_set']}) and {other['name']} on {other['stage_name']} "
                f"({facts['other_set']}) both need the {line['canonical_name']}, and the shared pool has "
                f"{line['quantity_total']}."
            )
            suggestion = (
                f"Hire a second unit, or agree a handover by moving one set so the windows do not overlap."
            )
            message, suggestion = ai.explain("double_booking", facts, message, suggestion)
            findings.append(Finding(kind="double_booking", severity="conflict", message=message,
                                    suggestion=suggestion, doc_id=line["doc_id"], quote=line["quote"],
                                    page=line["page"], facts=facts))
    return findings


def hospitality_total(artist_id: int) -> Decimal:
    with db.get_conn() as conn:
        items = _items(conn, artist_id, "hospitality")
    return sum((Decimal(str(i["unit_cost"])) * i["quantity"] for i in items if i["unit_cost"] is not None),
               Decimal("0"))


def hospitality_cap(artist: dict) -> Decimal:
    if artist.get("hospitality_cap") is not None:
        return Decimal(str(artist["hospitality_cap"]))
    return Decimal(str(load_rules("hospitality").get("default_cap", 0)))


def check_hospitality(artist_id: int) -> list[Finding]:
    findings: list[Finding] = []
    with db.get_conn() as conn:
        artist = _artist(conn, artist_id)
        items = _items(conn, artist_id, "hospitality")

    for it in items:
        if it["unit_cost"] is None:
            findings.append(Finding(
                kind="low_confidence", severity="info",
                message=f"No price on file for \"{it['raw_text']}\", so it is not in the hospitality total.",
                suggestion="Add a unit cost to hospitality.yaml or price it by hand.",
                doc_id=it["doc_id"], quote=it["quote"], page=it["page"],
            ))

    total, cap = hospitality_total(artist_id), hospitality_cap(artist)
    if total > cap:
        priced = [i for i in items if i["unit_cost"] is not None]
        biggest = max(priced, key=lambda i: i["unit_cost"] * i["quantity"])
        top = sorted(priced, key=lambda i: i["unit_cost"] * i["quantity"], reverse=True)[:3]
        facts = {"artist": artist["name"], "total": float(total), "cap": float(cap), "over": float(total - cap),
                 "largest_items": [f"{i['raw_text']} (${i['unit_cost'] * i['quantity']:,.0f})" for i in top]}
        message = f"Hospitality requests total ${total:,.0f}, the cap is ${cap:,.0f} (${total - cap:,.0f} over)."
        suggestion = f"Agree reductions with {artist['manager_name'] or 'the manager'}. Largest items: {', '.join(facts['largest_items'])}."
        message, suggestion = ai.explain("over_budget", facts, message, suggestion)
        findings.append(Finding(kind="over_budget", severity="warning", message=message, suggestion=suggestion,
                                doc_id=biggest["doc_id"], quote=biggest["quote"], page=biggest["page"],
                                facts=facts))
    return findings


def run_all(artist_id: int) -> list[Finding]:
    return check_shortage(artist_id) + check_double_booking(artist_id) + check_hospitality(artist_id)
