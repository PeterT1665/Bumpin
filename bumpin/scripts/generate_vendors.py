"""Write data/seed/vendors.json and data/seed/documents.json, and the vendor certificate PDFs.

Run from bumpin/:  .venv/bin/python scripts/generate_vendors.py

8 hand-crafted vendors plus 32 generated ones make 40. Every PDF has a real text layer.
Planted problems:
  4  Marlow Catering   food safety certificate expires 2026-12-05 (arrives by email, not on file)
  5  Smoke and Co      uses gas, no gas certificate (insurance arrives by email)
  8  Harbour Coffee Co load-in moves from Friday 07:00 to 05:30 (email only, docs are clean)
Output is deterministic so the seed files stay stable in git.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import fitz  # noqa: E402
from fpdf import FPDF  # noqa: E402

from backend.app.shared.llm import PageText  # noqa: E402
from backend.app.vendors.docs import fmt_date, parse_pages  # noqa: E402

PDF_DIR = ROOT / "data" / "docs" / "vendors"
SEED_DIR = ROOT / "data" / "seed"
FRIDAY = "2026-12-11"

# name, type, contact, email, uses_gas, zone, load_in start/end (HH:MM), status, docs on file
# docs: kind -> expiry ISO date. "email" docs are generated but not seeded.
HANDCRAFTED = [
    dict(name="Marlow Catering", type="food", contact="Tom Marlow", email="tom@marlowcatering.example.test",
         gas=0, zone="River Food Court", load=("07:30", "09:30"), status="in_progress",
         docs={"insurance": "2027-06-30", "permit": "2027-01-31"},
         email_docs={"food_safety": "2026-12-05"}),
    dict(name="Smoke and Co", type="food", contact="Jo Reyes", email="jo@smokeandco.example.test",
         gas=1, zone="Lawn Food Court", load=("08:00", "10:00"), status="in_progress",
         docs={"food_safety": "2027-05-20", "permit": "2027-01-31"},
         email_docs={"insurance": "2027-08-15"}),
    dict(name="Harbour Coffee Co", type="beverage", contact="Dana Cole", email="dana@harbourcoffee.example.test",
         gas=0, zone="Lawn Gate Cafe", load=("07:00", "09:00"), status="completed",
         docs={"insurance": "2027-04-30", "permit": "2027-01-31"}, email_docs={}),
    dict(name="Riverbend Tacos", type="food", contact="Mateo Ruiz", email="mateo@riverbendtacos.example.test",
         gas=1, zone="River Food Court", load=("09:00", "11:00"), status="completed",
         docs={"food_safety": "2027-07-01", "insurance": "2027-03-31", "permit": "2027-01-31", "gas": "2027-02-28"},
         email_docs={}),
    dict(name="Lawn Lemonade", type="beverage", contact="Ivy Chen", email="ivy@lawnlemonade.example.test",
         gas=0, zone="Lawn Gate Bar", load=("10:00", "12:00"), status="completed",
         docs={"insurance": "2027-05-31", "permit": "2027-01-31"}, email_docs={}),
    dict(name="Dome Disco Merch", type="merch", contact="Kai Brown", email="kai@domedisco.example.test",
         gas=0, zone="Dome Merch Row", load=("10:30", "12:00"), status="completed",
         docs={"insurance": "2027-09-30"}, email_docs={}),
    dict(name="Paper Crane Dumplings", type="food", contact="Lin Tran", email="lin@papercrane.example.test",
         gas=1, zone="Dome Food Court", load=("08:30", "10:30"), status="in_progress",
         docs={"food_safety": "2027-04-12", "insurance": "2027-06-30", "permit": "2027-01-31", "gas": "2027-03-15"},
         email_docs={}),
    dict(name="Fieldday Ice Co", type="other", contact="Bo Harris", email="bo@fielddayice.example.test",
         gas=0, zone="Main Gate Supplies", load=("06:00", "08:00"), status="completed",
         docs={"insurance": "2027-10-31", "permit": "2027-01-31"}, email_docs={}),
]

FIRST = ["Golden", "Sunny", "Salty", "Wild", "Little", "Big", "Smoky", "Fresh", "Crisp", "Lucky", "Red", "Blue",
         "Happy", "Hungry", "Sweet", "Spice", "Green", "Copper", "Quick", "Cosy"]
SECOND = ["Fork", "Spoon", "Barrow", "Skillet", "Ladle", "Basket", "Truck", "Cart", "Kitchen", "Oven", "Grill",
          "Press", "Pantry", "Stall", "Wagon", "Counter"]
CONTACTS = ["Alex Kim", "Jordan Lee", "Taylor Reid", "Casey Ng", "Morgan Shah", "Riley Park", "Jamie Fox",
            "Drew Patel", "Quinn Hart", "Avery Cole", "Rowan Bell", "Sasha Moore"]
ZONES = {
    "food": ["River Food Court", "Lawn Food Court", "Dome Food Court"],
    "beverage": ["River Bar Deck", "Lawn Gate Bar", "Dome Bar"],
    "merch": ["Main Gate Merch Row"],
    "other": ["Main Gate Supplies"],
}
GENERATED = 32
TYPE_MIX = ["food"] * 16 + ["beverage"] * 8 + ["merch"] * 5 + ["other"] * 3

ISSUERS = {
    "food_safety": "Riverside City Council Environmental Health",
    "insurance": "Southern Cross Underwriters",
    "permit": "Riverside City Council",
    "gas": "Harbourside Gas Compliance Services",
}


def slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_").replace("__", "_")


def long_date(iso: str) -> str:
    return fmt_date(iso)


def doc_pages(kind: str, vendor: str, expiry: str, number: str, cover: int = 20_000_000) -> list[list[tuple[str, str]]]:
    issuer = ISSUERS[kind]
    if kind == "food_safety":
        return [[
            ("h1", "FOOD SAFETY CERTIFICATE"),
            ("p", f"Issued by: {issuer}"),
            ("p", f"Business name: {vendor}"),
            ("p", f"Certificate no: {number}"),
            ("p", "Class of premises: Class 2 temporary food stall"),
            ("p", f"Valid until: {long_date(expiry)}"),
        ]]
    if kind == "insurance":
        return [[
            ("h1", "PUBLIC LIABILITY INSURANCE: CERTIFICATE OF CURRENCY"),
            ("p", f"Issued by: {issuer}"),
            ("p", f"Insured: {vendor}"),
            ("p", f"Policy no: {number}"),
            ("p", f"Cover: ${cover:,} any one occurrence"),
            ("p", f"Expiry date: {long_date(expiry)}"),
        ]]
    if kind == "permit":
        return [[
            ("h1", "TEMPORARY TRADING PERMIT"),
            ("p", f"Issued by: {issuer}"),
            ("p", f"Permit holder: {vendor}"),
            ("p", f"Permit no: {number}"),
            ("p", "Event: Riverside Festival, 11 to 13 December 2026"),
            ("p", f"Permit expires: {long_date(expiry)}"),
        ]]
    return [[
        ("h1", "GAS COMPLIANCE CERTIFICATE"),
        ("p", f"Issued by: {issuer}"),
        ("p", f"Installer for: {vendor}"),
        ("p", f"Certificate no: {number}"),
        ("p", "Appliances: LPG cooking equipment, compliant with current standards"),
        ("p", f"Valid until: {long_date(expiry)}"),
    ]]


def build_pdf(path: Path, pages: list[list[tuple[str, str]]]) -> None:
    pdf = FPDF(format="A4")
    pdf.set_creation_date(datetime(2026, 11, 1))
    pdf.set_auto_page_break(auto=True, margin=20)
    for blocks in pages:
        pdf.add_page()
        for kind, text in blocks:
            if kind == "h1":
                pdf.set_font("Helvetica", "B", 16)
                pdf.multi_cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(4)
            else:
                pdf.set_font("Helvetica", "", 12)
                pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def make_doc(vendor_name: str, kind: str, expiry: str, serial: int, cover: int) -> dict:
    """Write the PDF and return a documents seed row (text read back from the PDF)."""
    filename = f"{slug(vendor_name)}_{kind}.pdf"
    number = f"{kind[:2].upper()}-2026-{serial:04d}"
    path = PDF_DIR / filename
    build_pdf(path, doc_pages(kind, vendor_name, expiry, number, cover))
    with fitz.open(str(path)) as pdf:
        pages = [PageText(page=i, text=p.get_text()) for i, p in enumerate(pdf, start=1)]
    facts = parse_pages(pages)
    assert facts.kind == kind and facts.expiry_date == expiry, (vendor_name, kind, facts)
    return {
        "kind": kind, "filename": filename, "path": f"data/docs/vendors/{filename}",
        "extracted_text": "\n".join(p.text for p in pages), "expiry_date": facts.expiry_date,
        "issuer": facts.issuer,
    }


def main() -> None:
    rng = random.Random(2026)
    vendors: list[dict] = []
    documents: list[dict] = []
    serial = 100

    def add_vendor(spec: dict) -> None:
        nonlocal serial
        vid = len(vendors) + 1
        vendors.append({
            "id": vid, "name": spec["name"], "type": spec["type"], "contact_name": spec["contact"],
            "contact_email": spec["email"], "uses_gas": spec["gas"], "site_zone": spec["zone"],
            "load_in_start": f"{FRIDAY}T{spec['load'][0]}:00", "load_in_end": f"{FRIDAY}T{spec['load'][1]}:00",
            "status": spec["status"],
        })
        cover = 10_000_000 if spec["type"] == "merch" else 20_000_000
        for kind, expiry in spec["docs"].items():
            serial += 1
            row = make_doc(spec["name"], kind, expiry, serial, cover)
            documents.append({"owner_type": "vendor", "owner_id": vid, **row,
                              "received_at": f"2026-11-{rng.randint(3, 20):02d}T09:00:00"})
        for kind, expiry in spec.get("email_docs", {}).items():
            serial += 1
            make_doc(spec["name"], kind, expiry, serial, cover)  # attached to a demo email, not seeded

    for spec in HANDCRAFTED:
        add_vendor(spec)

    names = [f"{a} {b}" for a in FIRST for b in SECOND]
    rng.shuffle(names)
    for i in range(GENERATED):
        vtype = TYPE_MIX[i]
        name = names[i]
        gas = 1 if vtype == "food" and rng.random() < 0.35 else 0
        start_h = rng.choice([5, 6, 7, 8, 9, 10, 11])
        docs = {"insurance": f"2027-{rng.randint(3, 11):02d}-{rng.randint(1, 28):02d}"}
        if vtype in ("food", "beverage", "other"):
            docs["permit"] = f"2027-{rng.randint(1, 3):02d}-{rng.randint(10, 28):02d}"
        if vtype == "food":
            docs["food_safety"] = f"2027-{rng.randint(3, 11):02d}-{rng.randint(1, 28):02d}"
        if gas:
            docs["gas"] = f"2027-{rng.randint(2, 9):02d}-{rng.randint(1, 28):02d}"
        add_vendor(dict(
            name=name, type=vtype, contact=rng.choice(CONTACTS),
            email=f"hello@{slug(name).replace('_', '')}.example.test", gas=gas,
            zone=rng.choice(ZONES[vtype]), load=(f"{start_h:02d}:00", f"{start_h + 2:02d}:00"),
            status="completed" if i % 5 else "in_progress", docs=docs,
        ))

    (SEED_DIR / "vendors.json").write_text(json.dumps(vendors, indent=1) + "\n", encoding="utf-8")
    (SEED_DIR / "documents.json").write_text(json.dumps(documents, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(vendors)} vendors, {len(documents)} documents, PDFs in {PDF_DIR}")


if __name__ == "__main__":
    main()
