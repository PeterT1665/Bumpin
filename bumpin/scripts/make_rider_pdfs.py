"""Generate the hand-crafted rider PDFs (real text layer) into data/docs/riders/.

Run from bumpin/:  .venv/bin/python scripts/make_rider_pdfs.py
Planted problems: Sparkle (1, shortage), Halcyon (2, synth on file),
Marlow & The Lanes (3, over budget). Neon Tide's rider arrives pasted in an email.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parents[1] / "data" / "docs" / "riders"

RIDERS = {
    "sparkle_rider.pdf": [
        [
            ("h1", "SPARKLE: Technical and Hospitality Rider"),
            ("p", "Riverside Festival 2026, River Stage, Friday 11 December, 20:00 to 21:30"),
            ("p", "Management: Sam Ortiz, sam@sparkle-mgmt.example.test"),
            ("h2", "General"),
            ("p", "Sparkle performs a 90 minute DJ set with live visuals. Please allow 30 minutes for line check."),
            ("p", "All equipment must be set up and tested before doors. Technical requirements are on page 2."),
        ],
        [
            ("h2", "Technical requirements"),
            ("item", "3x Pioneer CDJ-3000"),
            ("note", "All decks linked via ethernet, latest firmware."),
            ("item", "1x Pioneer DJM-900NXS2"),
            ("item", "2x Monitor wedges"),
            ("item", "1x Shure SM58"),
            ("h2", "Hospitality"),
            ("item", "12x Bottled water"),
            ("item", "6x Towels"),
            ("item", "1x Fruit platter"),
        ],
    ],
    "halcyon_rider.pdf": [
        [
            ("h1", "HALCYON: Rider"),
            ("p", "Riverside Festival 2026, Lawn Stage, Saturday 12 December, 18:00 to 19:15"),
            ("p", "Management: Priya Nair, priya@halcyon-music.example.test"),
            ("h2", "Technical requirements"),
            ("item", "1x Moog One analog synth"),
            ("item", "1x Keyboard stand"),
            ("item", "2x Shure SM58"),
            ("item", "2x Monitor wedges"),
            ("h2", "Hospitality"),
            ("item", "8x Bottled water"),
            ("item", "1x Cheese platter"),
        ],
    ],
    "marlow_lanes_rider.pdf": [
        [
            ("h1", "MARLOW & THE LANES: Rider"),
            ("p", "Riverside Festival 2026, Lawn Stage, Sunday 13 December, 19:00 to 20:15"),
            ("p", "Management: Ada Brooks, ada@marlowlanes.example.test"),
            ("h2", "Technical requirements"),
            ("item", "4x Shure SM58"),
            ("item", "3x Monitor wedges"),
            ("h2", "Hospitality"),
            ("item", "1x Private dressing room"),
            ("item", "24x Premium beer"),
            ("item", "2x Bottle of champagne"),
            ("item", "1x Sushi platter"),
            ("item", "1x Cheese platter"),
            ("item", "12x Sparkling water"),
            ("item", "1x Fresh flowers"),
            ("item", "8x Hot meals"),
        ],
    ],
}


def build(filename: str, pages: list[list[tuple[str, str]]]) -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    for blocks in pages:
        pdf.add_page()
        for kind, text in blocks:
            if kind == "h1":
                pdf.set_font("Helvetica", "B", 18)
                pdf.multi_cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)
            elif kind == "h2":
                pdf.ln(4)
                pdf.set_font("Helvetica", "B", 13)
                pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
            elif kind == "item":
                pdf.set_font("Helvetica", "", 11)
                pdf.cell(8)
                pdf.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
            elif kind == "note":
                pdf.set_font("Helvetica", "I", 10)
                pdf.cell(14)
                pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.set_font("Helvetica", "", 11)
                pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
    pdf.output(str(OUT / filename))


def make_photo(pdf_name: str, page: int, out_name: str) -> None:
    """A phone-photo style JPEG of one rider page: slightly rotated, off-white, compressed."""
    import fitz
    from PIL import Image

    with fitz.open(str(OUT / pdf_name)) as pdf:
        pdf[page - 1].get_pixmap(dpi=110).save(str(OUT / "_page.png"))
    im = Image.open(OUT / "_page.png").convert("RGB").rotate(1.5, expand=True, fillcolor=(235, 232, 225))
    im.save(OUT / out_name, quality=55)
    (OUT / "_page.png").unlink()
    print("wrote", OUT / out_name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, pages in RIDERS.items():
        build(filename, pages)
        print("wrote", OUT / filename)
    make_photo("sparkle_rider.pdf", 2, "sparkle_rider_photo.jpg")


if __name__ == "__main__":
    main()
