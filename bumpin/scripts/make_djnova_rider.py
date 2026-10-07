"""Build the demo's hero rider: a handwritten page plus the manager's typed addendum.

WHAT IS ON DISK WHEN THIS FINISHES

  data/docs/riders/dj_nova_rider_handwritten.pdf   the supplied scan, copied in
  data/docs/riders/dj_nova_rider_handwritten.png   page 1 at 150 dpi, the FILED document
  data/docs/riders/dj_nova_addendum.pdf            the companion, built by make_rider_pdfs.build
  data/demo/djnova_ocr_raw.json                    what RapidOCR actually read, verbatim
  data/llm_cache/ocr_<sha256(png)[:24]>.json       the cache the backend reads

WHY AN IMAGE AND NOT THE PDF
`backend/app/artists/riders.py` branches on the file extension. A `.pdf` goes to
`extract_text`, which reads the PDF text layer; this scan has no text layer at all, so
that path yields nothing. An image goes to `ocr_image`. So page 1 is rendered to a PNG
and the PNG is what the email attaches. 150 dpi gives 1241x1754, the A4 aspect to the
pixel (595.28 x 841.89 pt at 150/72).

** THE TEXT IN THE CACHE IS A HUMAN TRANSCRIPTION. THE RECTS ARE MACHINE-MEASURED. **

That split is deliberate and it matters. RapidOCR locates the handwriting accurately but
cannot read it: on this page it returns "Pneer CJ-3000", "xPhoerMA-celmer",
"2 proesal bohmoniy spedbear". Nothing in that would alias-match the equipment manifest,
so no conflict could ever be derived and the hero ticket would be empty. So the rects are
taken from the OCR result untouched, line for line, and only the text is replaced with
what the page says when a person reads it. Every highlight therefore lands on the real
handwriting, because every rect was measured on the real handwriting.

`LINES` below pairs each corrected line with the garbled string OCR produced for it, and
the script refuses to write the cache unless the live OCR result still matches those
garbled strings in that order. If the renderer, the dpi or the OCR version ever moves,
this fails loudly instead of silently stapling the right words to the wrong boxes.

TWO LINES ON THE PAGE HAVE NO MEASURED RECT and are therefore absent from the cache:
"Hospitality:" and "6 x guest passes". OCR did not return a box for either at any dpi
tried (110, 150, 200, 260). A rect is not invented for them. The consequences are known
and harmless: the missing heading leaves the pass lines in the `technical` category, where
they match the manifest's accreditation rows rather than the hospitality price list, and
the missing "6 x guest passes" simply never becomes a rider line.

RE-RUNNING is safe and does not need OCR. The PNG render is deterministic, so the raw OCR
result is read back from `data/demo/djnova_ocr_raw.json` when its recorded image hash still
matches. OCR only runs again if the image changes.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

import pymupdf
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.make_rider_pdfs import build  # noqa: E402  same text layer as every other rider

SOURCE_PDF = pathlib.Path(
    "/Users/jordanrusli/Desktop/Second Brain/Projects/Affinda Hackathon/Focus/DJ NOVA.pdf")

RIDER_DIR = ROOT / "data" / "docs" / "riders"
SCAN_PDF = RIDER_DIR / "dj_nova_rider_handwritten.pdf"
SCAN_PNG = RIDER_DIR / "dj_nova_rider_handwritten.png"
ADDENDUM = "dj_nova_addendum.pdf"
RAW_OCR = ROOT / "data" / "demo" / "djnova_ocr_raw.json"
CACHE_DIR = ROOT / "data" / "llm_cache"

DPI = 150

#: (what RapidOCR read, what the page says). Index order is OCR's own order, which is
#: top to bottom. The left column is evidence, not input: it is compared against a live
#: OCR run and the script aborts on any difference.
LINES = [
    # The page is in block capitals because it is handwriting on notepaper. The act is
    # "Dj Nova"; this column is the transcription of what is written, not the name.
    ("DJ NOVA",                                          "DJ NOVA"),
    ("Lveset,g9mntes",                                   "Live set, 90 minutes"),
    ("Stave:",                                           "Stage:"),
    ("Pneer CJ-3000",                                    "4 x Pioneer CDJ-3000"),
    ("xPhoerMA-celmer",                                  "1 x Pioneer DJM-A9 4-channel mixer"),
    ("2 proesal bohmoniy spedbear",                      "2 x professional booth monitor speaker"),
    ("xmicrophnewih stanol",                             "1 x microphone with stand"),
    ("All eaupnat fill kese ondcerhnd epurho arstomlul",
     "All equipment fully tested and operational prior to artist arrival"),
    ("Mahy-heal ans",                                    "Moving-head lights"),
    ("Sde liahts",                                       "Strobe lights"),
    ("Fa/smole Machhes x2",                              "Fog/smoke machines x2"),
    ("Jsina aay fer 6:Shll& gprkiy wter set doks",
     "Dressing room for 6; Still & sparkling water, soft drinks,"),
    ("fieh frut ond sndes.Hotmed fr 4by18:00",
     "fresh fruit and snacks. Hot meal for 4 by 18:00"),
    ("4xbodkshae psses",                                 "4 x backstage passes"),
    ("Ix prchng space",                                  "1 x parking space"),
]

#: On the page but with no rect OCR would give up, so deliberately not in the cache.
NO_RECT = ["Hospitality:", "6 x guest passes"]

# --- widening a line rect back to where the writing starts ---------------------------
#
# RapidOCR boxes the part of the line it managed to read, which on this page is the item
# name and not the count in front of it: its rect for "4 x Pioneer CDJ-3000" starts at
# x=237, which is to the right of the "4 x". A highlight that covers the item but not the
# quantity points at the wrong thing, because the quantity is what is in dispute.
#
# So each rect is extended leftward to where the line's ink actually begins, MEASURED off
# the image rather than shifted by a guessed constant:
#
#   INK          a pixel whose brightest channel is below INK_MAX. The handwriting runs
#                130 to 200 on that measure and the paper runs 245 to 255, so the two do
#                not overlap. The red margin rule is excluded for free: its red channel is
#                far above the threshold.
#   RULED ROWS   a printed rule crosses the whole page, so every column in the band would
#                register ink and the walk would never stop. Any row that is ink across
#                more than RULE_ROW_FRACTION of the page is a rule, and is dropped from
#                the band before the walk.
#   BAND         the middle 40% of the rect's height, not all of it. This handwriting
#                slants, so consecutive OCR rects overlap vertically by up to 21 rows:
#                with the full height the walk kept finding the NEIGHBOURING line's ink
#                in the blanks and ran all the way to the margin. Four of the fifteen
#                lines did. The middle band holds this line's x-height and almost none
#                of its neighbours', and no line reaches the floor any more.
#   THE WALK     starting at the OCR rect's own left edge, step left one column at a time,
#                remembering the last column that held ink. Stop after MAX_GAP consecutive
#                blank columns. On this page the widest gap inside a line (bullet to
#                quantity, quantity to item name) is 14 columns and the blank run between
#                the bullet and the margin rule is 33, so 26 separates them cleanly.
#   FLOOR        the walk never passes the red margin rule, found as the reddest column in
#                the left third of the page. Nothing is written to the left of it, and the
#                photographer's thumb is.
#
# Each widened rect is checked: the OCR rect must hold ink SOMEWHERE inside it (OCR read
# a line there, so if the threshold finds nothing the threshold is wrong for this image),
# and the result must stay right of the floor. The left edge itself is not probed: three
# of these rects open in the gap between the bullet and the quantity, which is exactly the
# gap this is here to close.
INK_MAX = 195
RULE_ROW_FRACTION = 0.5
MAX_GAP = 26
BAND_INSET = 0.30            # see BAND below
FLOOR_PAD = 4


def _margin_column(px, w, h):
    """The red ruled margin, as the column with the most strongly red pixels."""
    best, best_n = 0, -1
    for x in range(w // 3):
        n = sum(1 for y in range(0, h, 7)
                if px[x, y][0] > 140 and px[x, y][0] - px[x, y][1] > 45 and px[x, y][0] - px[x, y][2] > 30)
        if n > best_n:
            best, best_n = x, n
    return best


def widen_left(rects):
    """Extend every rect leftward to the first ink on its line. Returns (rects, report)."""
    with Image.open(SCAN_PNG) as img:
        im = img.convert("RGB")
    w, h = im.size
    px = im.load()
    floor = _margin_column(px, w, h) + FLOOR_PAD

    ink_cols = [[x for x in range(w) if max(px[x, y]) < INK_MAX] for y in range(h)]
    ruled = {y for y in range(h) if len(ink_cols[y]) > RULE_ROW_FRACTION * w}

    out, report = [], []
    for rect in rects:
        x0, y0, x1, y1 = rect
        inset = (y1 - y0) * BAND_INSET
        band = [y for y in range(max(0, int(y0 + inset)), min(h, int(y1 - inset))) if y not in ruled]
        hit = lambda x: any(max(px[x, y]) < INK_MAX for y in band)       # noqa: E731
        if not band or not any(hit(x) for x in range(int(x0), int(x1) + 1)):
            raise SystemExit(
                f"rect {rect}: no ink at the OCR edge itself, so INK_MAX={INK_MAX} does not "
                f"separate this image's writing from its paper. Refusing to widen by guesswork.")
        found, gap = int(x0), 0
        for x in range(int(x0) - 1, floor - 1, -1):
            if hit(x):
                found, gap = x, 0
            else:
                gap += 1
                if gap > MAX_GAP:
                    break
        assert found >= floor, f"{rect} walked past the margin rule at {floor}"
        out.append([float(found), y0, x1, y1])
        report.append((x0, float(found)))
    return out, report

#: The manager's typed companion, sent in the same email as the photo. Built through
#: `make_rider_pdfs.build` so the font, the page geometry and the content-stream shape
#: match every other rider PDF; `enrich_highlights` derives rects from that geometry and
#: aborts if it changes.
#:
#: Quantities are read against data/demo/initial/riverside_equipment_manifest.csv, not
#: guessed. Dj Nova plays the Dome, which owns 4 Shure SM58 and 2 monitor wedges:
#:   6x Shure SM58     -> shortage, 6 against 4. THE CONFLICT THIS DOCUMENT CONTRIBUTES.
#:   2x Monitor wedge  -> exactly the Dome's stock, clean
#:   1x Keyboard stand -> 1 of the 2 shared stands, and no overlapping set wants one
#: Hospitality is priced in data/rules/hospitality.yaml and comes to $72 against a
#: $1,000 cap, so it raises nothing.
ADDENDUM_PAGES = [[
    ("h1", "Dj Nova: Technical addendum"),
    ("p", "Riverside Festival 2026, Dome Stage, Saturday 12 December, 20:15 to 21:45"),
    ("p", "Management: Mira Okafor, mira@djnova.example.test"),
    ("p", "This sheet supersedes nothing. It lists what the handwritten page leaves out."),
    ("h2", "Technical requirements"),
    ("item", "6x Shure SM58"),
    ("note", "Four across the front for the vocal feature, two spares at the booth."),
    ("item", "2x Monitor wedge"),
    ("item", "1x Keyboard stand"),
    ("h2", "Hospitality"),
    ("item", "6x Bottled water"),
    ("item", "1x Fruit platter"),
]]


def render_scan() -> str:
    """Copy the supplied scan in and render page 1 to a PNG. Returns the PNG's hash."""
    RIDER_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCE_PDF.exists() and not SCAN_PDF.exists():
        raise SystemExit(f"handwritten rider not found at {SOURCE_PDF} and not already copied in")
    if SOURCE_PDF.exists():
        shutil.copyfile(SOURCE_PDF, SCAN_PDF)
    with pymupdf.open(str(SCAN_PDF)) as pdf:
        page = pdf[0]
        if page.get_text().strip():
            raise SystemExit("page 1 has a text layer after all — file the PDF, not an image")
        page.get_pixmap(dpi=DPI).save(str(SCAN_PNG))
    return hashlib.sha256(SCAN_PNG.read_bytes()).hexdigest()[:24]


def measure(image_hash: str) -> dict:
    """The raw OCR result: one rect and one garbled string per line, straight from RapidOCR.

    Read back from disk when the image has not changed, so a demo re-run never waits on
    the ONNX engine. The file is the provenance record for every rect in the cache.
    """
    if RAW_OCR.exists():
        raw = json.loads(RAW_OCR.read_text(encoding="utf-8"))
        if raw.get("image_sha256_24") == image_hash:
            print(f"  raw OCR read back from {RAW_OCR.name} ({len(raw['lines'])} lines)")
            return raw
        print(f"  !! {RAW_OCR.name} was measured on a different image, re-running OCR")

    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    # Same engine, same confidence floor as backend/app/artists/riders.py:ocr_image, so
    # what is recorded here is exactly what the backend would have cached on a cold run.
    result, _ = RapidOCR()(str(SCAN_PNG))
    with Image.open(SCAN_PNG) as im:
        size = list(im.size)
    lines = []
    for box, text, conf in result or []:
        if float(conf) < 0.4:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append({"text": text, "confidence": round(float(conf), 3),
                      "rect": [round(min(xs), 1), round(min(ys), 1),
                               round(max(xs), 1), round(max(ys), 1)]})
    raw = {"image": str(SCAN_PNG.relative_to(ROOT)), "image_sha256_24": image_hash,
           "dpi": DPI, "size": size, "engine": "rapidocr_onnxruntime", "lines": lines}
    RAW_OCR.parent.mkdir(parents=True, exist_ok=True)
    RAW_OCR.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    print(f"  ran RapidOCR, wrote {RAW_OCR.name} ({len(lines)} lines)")
    return raw


def write_cache(raw: dict, image_hash: str) -> pathlib.Path:
    """Measured rects, transcribed text. Refuses on any drift in the measurement."""
    if len(raw["lines"]) != len(LINES):
        raise SystemExit(f"OCR returned {len(raw['lines'])} lines, LINES describes {len(LINES)}")
    for i, (line, (garbled, _)) in enumerate(zip(raw["lines"], LINES)):
        if line["text"] != garbled:
            raise SystemExit(
                f"line {i}: OCR now reads {line['text']!r}, LINES was written against "
                f"{garbled!r}. Re-check the transcription against the page before editing this.")

    rects, report = widen_left([l["rect"] for l in raw["lines"]])
    print("  rect left edges, OCR measurement -> ink measurement:")
    for (before, after), (_, corrected) in zip(report, LINES):
        moved = "" if before == after else f"  <- widened by {before - after:.0f}px"
        print(f"    x0 {before:>7.1f} -> {after:<7.1f} {corrected[:46]!r}{moved}")
    data = {"size": raw["size"],
            "lines": [{"text": corrected, "rect": rect}
                      for rect, (_, corrected) in zip(rects, LINES)]}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"ocr_{image_hash}.json"
    cache.write_text(json.dumps(data), encoding="utf-8")
    return cache


def main() -> None:
    print("Dj Nova, the handwritten rider")
    image_hash = render_scan()
    print(f"  {SCAN_PNG.relative_to(ROOT)}  sha256[:24]={image_hash}")
    raw = measure(image_hash)
    cache = write_cache(raw, image_hash)
    print(f"  {cache.relative_to(ROOT)}  {len(LINES)} lines, rects measured, text transcribed")
    for name in NO_RECT:
        print(f"  !! {name!r} is on the page but OCR measured no rect for it, so it is not cached")

    build(ADDENDUM, ADDENDUM_PAGES)
    print(f"  {(RIDER_DIR / ADDENDUM).relative_to(ROOT)}  the typed companion")


if __name__ == "__main__":
    main()
