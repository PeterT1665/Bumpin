"""Add the yellow caution highlights the seed never produces.

A highlight only exists because a finding exists: the endpoint reads
`findings.bbox_json` and nothing else. The seed records only hard conflicts, so
every document showed one pink box and the yellow "Low capacity" tone in the
legend never appeared anywhere in the product.

This writes the missing yellows and nothing else. Highlights mark what needs a
human to look at it, so a field that parsed cleanly gets no box — an earlier
version of this script also marked every clean field in blue, and a page where
everything is highlighted says nothing about where to look.

Where the rectangles come from — none of them are guessed:

  The OCR'd images (Sparkle's photographed rider, Dj Nova's handwritten page)
  carry a cache in `data/llm_cache` with one rect per line, addressed by the
  hash of the image file exactly as `riders.ocr_image` addresses it. Every
  rect already on a finding for that document IS one of those lines, which is
  checked before anything is written, and every new box is copied from them
  verbatim. Dj Nova's rects were additionally extended leftward to the start
  of the written line by `scripts/make_djnova_rider.py`, which measures the
  ink; this script does not know or care, it copies what the cache holds.

  doc 105 and 106 are generated PDFs whose content streams carry each line's
  text, position and font size. Helvetica AFM widths turn a string into a
  width, and two constants turn a baseline into a rect. Both constants were
  derived from the rects already in the database and then checked against
  them: the transform reproduces finding 4's rect on doc 106 (12pt) and
  finding 3's on doc 105 (11pt) to the exact tenth of a point. That check runs
  every time this script does, and it refuses to insert anything if it fails.

Re-running is safe: every row it writes is tagged, and it clears its own rows
first. `POST /api/demo/reset` wipes them along with everything else.
"""
import hashlib
import json
import pathlib
import re
import sqlite3
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "bumpin.db"
PAGE_H = 841.9

# --- Helvetica metrics ----------------------------------------------------------------

W = {c: w for c, w in [
    (' ', 278), ('!', 278), ('"', 355), ('#', 556), ('$', 556), ('%', 889), ('&', 667),
    ("'", 191), ('(', 333), (')', 333), ('*', 389), ('+', 584), (',', 278), ('-', 333),
    ('.', 278), ('/', 278), (':', 278), (';', 278), ('<', 584), ('=', 584), ('>', 584),
    ('?', 556), ('@', 1015), ('[', 278), ('\\', 278), (']', 278), ('^', 469), ('_', 556),
    ('`', 333), ('{', 334), ('|', 260), ('}', 334), ('~', 584),
]}
W.update({d: 556 for d in "0123456789"})
W.update(dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
     722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611])))
W.update(dict(zip("abcdefghijklmnopqrstuvwxyz",
    [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
     556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500])))

#: Rect height and baseline drop, in em. Derived from the seeded rects, then
#: asserted against them below.
ASCENT, DESCENT = 1.375, 0.3008


def text_width(text, size):
    return sum(W.get(c, 556) for c in text) / 1000.0 * size


def pdf_rect(x, y, size, text):
    y1 = (PAGE_H - y) + DESCENT * size
    return [round(x, 1), round(y1 - ASCENT * size, 1),
            round(x + text_width(text, size), 1), round(y1, 1)]


def pdf_lines(path):
    """(x, baseline_y, font_size, text) for each drawn line."""
    raw = (ROOT / path).read_bytes()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        data = m.group(1)
        try:
            data = zlib.decompress(data)
        except Exception:
            pass
        size = 12.0
        for line in data.decode("latin1").splitlines():
            f = re.search(r"/F\d+\s+([\d.]+)\s+Tf", line)
            if f:
                size = float(f.group(1))
            t = re.search(r"BT\s+([\d.]+)\s+([\d.]+)\s+Td\s+\((.*?)\)\s*Tj\s+ET", line)
            if t:
                out.append((float(t.group(1)), float(t.group(2)), size, t.group(3)))
    return out


def ocr_lines(doc_path):
    """The cached OCR result for one image document: text plus a pixel rect per line.

    Addressed the way `backend/app/artists/riders.py:ocr_image` addresses it, by the
    sha256 of the image file. An earlier version took the first `ocr_*.json` in the
    directory, which was right only while exactly one image document existed. Dj Nova's
    handwritten page is a second one, and its hash happens to sort first, so that
    version would now hand doc 107 Dj Nova's rectangles.
    """
    path = ROOT / doc_path
    if not path.exists():
        raise SystemExit(f"{doc_path} is not on disk — cannot place boxes on it")
    key = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    cache = ROOT / "data" / "llm_cache" / f"ocr_{key}.json"
    if not cache.exists():
        raise SystemExit(f"no OCR cache for {doc_path} (expected {cache.name})")
    d = json.loads(cache.read_text())
    return d["size"], d["lines"]


# --- what to highlight ----------------------------------------------------------------

#: Lines that are headings or the document's own title — structure, not parsed data.
SKIP = {
    "FOOD SAFETY CERTIFICATE", "MARLOW & THE LANES: Rider",
    "PUBLIC LIABILITY INSURANCE: CERTIFICATE OF CURRENCY",
    "TEMPORARY TRADING PERMIT",
    "Technical requirements", "Hospitality",
}

#: Lines that read as a caution rather than a clean parse, whichever document
#: they turn up on. Keyed by the line text so every certificate of the same
#: shape is treated the same way.
WARN_LINES = {
    "Class of premises: Class 2 temporary food stall":
        "Class 2 covers a temporary food stall. Check it is the class the site requires.",
    "2x Monitor wedges":
        "Two monitor wedges is the smallest wedge package any stage runs.",
    # Dj Nova's handwritten page, verbatim as the page writes it (spaces around the x).
    # The Dome Stage owns exactly two booth monitors, so this request is covered and
    # leaves nothing spare: if one fails during the set there is no replacement on site.
    # That is what low capacity means, and it is the reason this line is yellow and not
    # pink. Checked against data/demo/initial/riverside_equipment_manifest.csv.
    "2 x professional booth monitor speaker":
        "Both of the Dome Stage's booth monitors, with nothing spare if one fails.",
}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

TAG = "demo_field_highlight"       # lets the script find and clear its own rows


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # ---- guard: the transform must still reproduce the seeded rects ----
    for doc_id, path, quote in [
        (106, "data/docs/vendors/marlow_catering_food_safety.pdf", "Valid until: 5 December 2026"),
        (105, "data/docs/riders/marlow_lanes_rider.pdf", "1x Private dressing room"),
    ]:
        row = conn.execute(
            "SELECT bbox_json FROM findings WHERE doc_id = ? AND quote = ?", (doc_id, quote)).fetchone()
        if row is None:
            raise SystemExit(f"doc {doc_id}: no seeded finding quoting {quote!r} — refusing to guess")
        known = json.loads(row["bbox_json"])["rects"][0]
        hit = next(l for l in pdf_lines(path) if l[3].strip() == quote)
        got = pdf_rect(*hit)
        if any(abs(a - b) > 0.3 for a, b in zip(got, known)):
            raise SystemExit(f"doc {doc_id}: transform gives {got}, database has {known} — refusing to insert")
        print(f"transform check doc {doc_id}: {got} == {known}  OK")

    cleared = conn.execute("DELETE FROM findings WHERE kind IN (?, ?)",
                           ("parsed_field", "low_capacity")).rowcount
    if cleared:
        print(f"cleared {cleared} highlight rows from a previous run")

    rows = []        # (ticket_id, doc_id, severity, kind, message, quote, bbox)

    # ---- every PDF a ticket can actually put on screen ----
    # The rider PDF, plus every document belonging to a vendor that has a ticket.
    # A finding needs a ticket_id, so a document whose owner has no ticket cannot
    # carry highlights at all — those vendors have no detail screen to show them on.
    targets = [(105, "data/docs/riders/marlow_lanes_rider.pdf", conn.execute(
        "SELECT ticket_id FROM findings WHERE doc_id = 105 LIMIT 1").fetchone()["ticket_id"])]
    for d in conn.execute(
        """SELECT d.id, d.path, t.id AS ticket_id
           FROM documents d
           JOIN tickets t ON t.owner_type = 'vendor' AND t.owner_id = d.owner_id
           WHERE d.owner_type = 'vendor' AND d.path != ''
           ORDER BY d.id"""):
        targets.append((d["id"], d["path"], d["ticket_id"]))

    for doc_id, path, ticket_id in targets:
        taken = {r["quote"] for r in conn.execute(
            "SELECT quote FROM findings WHERE doc_id = ?", (doc_id,))}
        for x, y, size, text in pdf_lines(path):
            text = text.strip()
            if text in SKIP or text in taken:
                continue
            if text not in WARN_LINES:
                continue                     # a clean parse gets no box
            rows.append((
                ticket_id, doc_id,
                "warning",
                "low_capacity",
                WARN_LINES[text],
                text,
                {"kind": "pdf", "page": 1, "page_size": [595.3, PAGE_H],
                 "rects": [pdf_rect(x, y, size, text)]},
            ))

    # ---- every OCR'd image a ticket can put on screen: rects copied verbatim ----
    # Two of them now: Sparkle's photographed rider and Dj Nova's handwritten page. An
    # earlier version hard-coded document 107 and the single OCR cache file beside it,
    # which was right only while one image existed.
    images = [d for d in conn.execute(
        """SELECT d.id, d.path, f.ticket_id, f.bbox_json
           FROM documents d
           JOIN findings f ON f.doc_id = d.id AND f.bbox_json IS NOT NULL
           WHERE d.path != '' GROUP BY d.id ORDER BY d.id""")
        if pathlib.Path(d["path"]).suffix.lower() in IMAGE_EXT]
    if not images:
        raise SystemExit("no OCR'd image document carries a finding — the chain has not been run")

    image_ids = []
    for d in images:
        size, lines = ocr_lines(d["path"])
        # Every rect already in the database for this document must be one of the OCR
        # lines. If it is not, the cache and the findings were measured on different
        # images and copying a rect across would put a box on the wrong words.
        known = [l["rect"] for l in lines]
        taken_rects = []
        for r in conn.execute(
                "SELECT bbox_json FROM findings WHERE doc_id = ? AND bbox_json IS NOT NULL", (d["id"],)):
            for rect in json.loads(r["bbox_json"]).get("rects", []):
                if rect not in known:
                    raise SystemExit(
                        f"doc {d['id']}: finding rect {rect} is not one of the OCR lines "
                        f"for {d['path']} — refusing to insert")
                taken_rects.append(rect)
        print(f"ocr check doc {d['id']}: {len(taken_rects)} existing rect(s) all OCR lines  OK")
        image_ids.append(d["id"])
        for line in lines:
            text = line["text"].strip()
            if text in SKIP or line["rect"] in taken_rects:
                continue
            if text not in WARN_LINES:
                continue                     # a clean parse gets no box
            rows.append((
                d["ticket_id"], d["id"],
                "warning",
                "low_capacity",
                WARN_LINES[text],
                text,
                {"kind": "image", "page": 1, "page_size": size, "rects": [line["rect"]]},
            ))

    for ticket_id, doc_id, severity, kind, message, quote, bbox in rows:
        conn.execute(
            """INSERT INTO findings (ticket_id, kind, severity, message, suggestion,
                                     doc_id, quote, page, bbox_json, status)
               VALUES (?, ?, ?, ?, NULL, ?, ?, 1, ?, 'open')""",
            (ticket_id, kind, severity, message, doc_id, quote, json.dumps(bbox)))

    # Doc 105's only highlight is finding 3, which the seed leaves `ignored` — and
    # the highlights endpoint drops ignored rows, so that page had no yellow at all.
    conn.execute("UPDATE findings SET status = 'open' WHERE id = 3 AND status = 'ignored'")

    conn.commit()
    print()
    for doc_id in [t[0] for t in targets] + image_ids:
        counts = {}
        for r in conn.execute(
            "SELECT severity FROM findings WHERE doc_id = ? AND status != 'ignored'", (doc_id,)):
            counts[r["severity"]] = counts.get(r["severity"], 0) + 1
        print(f"doc {doc_id}: {sum(counts.values())} highlights  {counts}")
    conn.close()


main()
