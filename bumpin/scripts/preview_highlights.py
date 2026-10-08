"""Build data/preview/highlights.html: the planted problems drawn the way the frontend will.

Run from bumpin/:  .venv/bin/python scripts/preview_highlights.py
Uses a throwaway database and the real /api endpoints (file and highlights), then draws
the boxes by scaling rect / page_size, and underlines text spans. Open the HTML in a browser.
"""

from __future__ import annotations

import base64
import html
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["BUMPIN_DB"] = os.path.join(tempfile.mkdtemp(), "preview.db")

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import db  # noqa: E402
from backend.app.artists import ripple, tickets  # noqa: E402
from backend.app.main import app  # noqa: E402

OUT = ROOT / "data" / "preview" / "highlights.html"
CLS = SimpleNamespace(confidence=0.95, entity_hint=None, is_major_change=False)
COLOR = {"conflict": "#d92d20", "warning": "#dc6803", "info": "#175cd3"}


def receive(from_addr: str, body: str, attachment: str | None = None, subject: str = "Rider") -> int:
    with db.get_conn() as conn:
        eid = conn.execute(
            "INSERT INTO emails (direction, from_addr, subject, body, received_at) VALUES ('in', ?, ?, ?, ?)",
            (from_addr, subject, body, "2026-11-30T10:00:00")).lastrowid
        if attachment:
            conn.execute(
                """INSERT INTO documents (owner_type, owner_id, kind, filename, path, received_at, email_id)
                   VALUES ('artist', 0, 'other', ?, ?, ?, ?)""",
                (Path(attachment).name, attachment, "2026-11-30T10:00:00", eid))
    return eid


def findings(ticket_id: int) -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT * FROM findings WHERE ticket_id = ?", (ticket_id,)))


def data_uri(png: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(png).decode()}"


def overlay(img_uri: str, boxes: list[dict]) -> str:
    """Draw boxes as percentages of page_size, exactly what the frontend does."""
    divs = ""
    for b in boxes:
        x0, y0, x1, y1 = b["rect"]
        w, h = b["page_size"]
        c = COLOR[b["severity"]] if b["status"] == "open" else "#98a2b3"
        divs += (f'<div class="box" style="left:{100*x0/w:.3f}%;top:{100*y0/h:.3f}%;width:{100*(x1-x0)/w:.3f}%;'
                 f'height:{100*(y1-y0)/h:.3f}%;border-color:{c};background:{c}22"></div>')
    return f'<div class="page"><img src="{img_uri}">{divs}</div>'


def underline(text: str, boxes: list[dict]) -> str:
    out, pos = "", 0
    for b in sorted(boxes, key=lambda b: b["start"]):
        c = COLOR[b["severity"]] if b["status"] == "open" else "#98a2b3"
        out += html.escape(text[pos:b["start"]])
        out += f'<span class="ul" style="text-decoration-color:{c}">{html.escape(text[b["start"]:b["end"]])}</span>'
        pos = b["end"]
    return out + html.escape(text[pos:])


def card(title: str, formats: str, message: str, body: str) -> str:
    return (f'<section><h2>{html.escape(title)}</h2><p class="meta">{formats}</p>'
            f'<p class="msg">{html.escape(message)}</p>{body}</section>')


def main() -> None:
    db.reset()
    cards = []
    with TestClient(app) as client:
        def boxes_for(doc_id: int) -> list[dict]:
            return client.get(f"/api/documents/{doc_id}/highlights").json()

        # 1. PDF: Sparkle shortage
        tid = tickets.create_rider_ticket(
            receive("sam@sparkle-mgmt.example.test", "see attached", "data/docs/riders/sparkle_rider.pdf"), CLS)
        f = next(x for x in findings(tid) if x["kind"] == "shortage")
        boxes = boxes_for(f["doc_id"])
        with fitz.open(stream=client.get(f"/api/documents/{f['doc_id']}/file").content, filetype="pdf") as pdf:
            png = pdf[boxes[0]["page"] - 1].get_pixmap(dpi=100).tobytes("png")
        cards.append(card("Problem 1: Sparkle, PDF rider", f"type {boxes[0]['type']}, page {boxes[0]['page']}",
                          f["message"], overlay(data_uri(png), boxes)))

        # 1b. Photo: same rider as a phone photo, read by OCR
        tid = tickets.create_rider_ticket(
            receive("sam@sparkle-mgmt.example.test", "photo of the printed rider",
                    "data/docs/riders/sparkle_rider_photo.jpg"), CLS)
        f = next(x for x in findings(tid) if x["kind"] == "shortage")
        boxes = boxes_for(f["doc_id"])
        jpg = client.get(f"/api/documents/{f['doc_id']}/file").content
        cards.append(card("Problem 1 as a photo: Sparkle, JPEG rider read by OCR",
                          f"type {boxes[0]['type']}, boxes in image pixels", f["message"],
                          overlay(data_uri(jpg, "image/jpeg"), boxes)))

        # 2. Plain email: Neon Tide pasted rider
        body = ("Hey team, pasting Neon Tide's rider below.\n\nTECH\n1x Analogue synth (Moog One)\n"
                "2x CDJ-2000NXS2\n2x wedges\n\nHOSPO\n6x bottled water\n1x fruit platter\n\nCheers, Leo")
        tid = tickets.create_rider_ticket(receive("leo@neontide.example.test", body), CLS)
        f = next(x for x in findings(tid) if x["kind"] == "double_booking")
        text = client.get(f"/api/documents/{f['doc_id']}/file").text
        cards.append(card("Problem 2: Neon Tide, rider pasted in an email", "type text, underlined",
                          f["message"], f'<pre class="mail">{underline(text, boxes_for(f["doc_id"]))}</pre>'))

        # 6. Plain email: Nova Lane
        eid = receive("chris@novalane.example.test",
                      "Hi Ravi, bad news: our flight from Sydney has been cancelled. We are rebooked and land at "
                      "9:40pm, so Nova Lane cannot make the 21:15 set. Chris", subject="Flight cancelled")
        tid = ripple.create_help_ticket(eid, SimpleNamespace(confidence=0.95, entity_hint="Nova Lane",
                                                             is_major_change=True, label="help_or_change"))
        f = findings(tid)[0]
        text = client.get(f"/api/documents/{f['doc_id']}/file").text
        cards.append(card("Problem 6: Nova Lane, flight cancelled", "type text, underlined", f["message"],
                          f'<pre class="mail">{underline(text, boxes_for(f["doc_id"]))}</pre>'))

        # 7. Plain email: vague request, low confidence
        eid = receive("priya@halcyon-music.example.test",
                      "Hey, this is Halcyon's manager. Could we maybe go on a bit later? Nothing urgent, just "
                      "wondering if there's any flexibility. Cheers.", subject="Set time")
        tid = ripple.create_help_ticket(eid, SimpleNamespace(confidence=0.5, entity_hint="Halcyon",
                                                             is_major_change=True, label="help_or_change"))
        f = findings(tid)[0]
        text = client.get(f"/api/documents/{f['doc_id']}/file").text
        cards.append(card("Problem 7: Halcyon, vague request (low confidence, review list)",
                          "type text, underlined", f["message"],
                          f'<pre class="mail">{underline(text, boxes_for(f["doc_id"]))}</pre>'))

        # 3. PDF: Marlow hospitality
        tid = tickets.create_rider_ticket(
            receive("ada@marlowlanes.example.test", "see attached", "data/docs/riders/marlow_lanes_rider.pdf"), CLS)
        f = next(x for x in findings(tid) if x["kind"] == "over_budget")
        boxes = boxes_for(f["doc_id"])
        with fitz.open(stream=client.get(f"/api/documents/{f['doc_id']}/file").content, filetype="pdf") as pdf:
            png = pdf[boxes[0]["page"] - 1].get_pixmap(dpi=100).tobytes("png")
        cards.append(card("Problem 3: Marlow & The Lanes, over budget (warning, orange)",
                          f"type {boxes[0]['type']}", f["message"], overlay(data_uri(png), boxes)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><title>BumpIn highlight preview</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#101828}}
h1{{font-size:22px}} section{{border:1px solid #d0d5dd;border-radius:10px;padding:16px;margin:20px 0}}
h2{{font-size:17px;margin:0 0 2px}} .meta{{color:#667085;margin:0 0 8px;font-size:13px}} .msg{{margin:0 0 12px}}
.page{{position:relative;display:inline-block;max-width:100%;border:1px solid #d0d5dd}} .page img{{display:block;max-width:100%}}
.box{{position:absolute;border:2px solid;box-sizing:border-box;border-radius:3px}}
.mail{{white-space:pre-wrap;background:#f9fafb;border:1px solid #eaecf0;border-radius:8px;padding:12px;font:14px/1.6 ui-monospace,monospace}}
.ul{{text-decoration:underline;text-decoration-thickness:3px;text-underline-offset:4px;background:#fef3f2}}
</style></head><body><h1>BumpIn highlight preview</h1>
<p>Built from the real <code>/api/documents/&#123;id&#125;/file</code> and <code>/highlights</code> responses. Red is a conflict, orange a warning.</p>
{''.join(cards)}</body></html>""", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
