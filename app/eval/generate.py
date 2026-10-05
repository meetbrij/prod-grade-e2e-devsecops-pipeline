"""Generates the synthetic golden set: fictional ID cards and proofs of address.

Everything here is invented. There is no real person, no real issuer and no real country:
IDs come from the fictional "Republic of Examplia", numbers start with SPC, and every
document carries a diagonal SPECIMEN watermark. Do not use these images for anything other
than testing extraction accuracy.

    python -m eval.generate [--out eval/golden]

The output (images plus labels.json) is committed, so running the eval does not need Pillow.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SEED = 20261005
TODAY = date(2026, 10, 5)

FIRST = [
    "Omar",
    "Layla",
    "Rahul",
    "Priya",
    "Ahmed",
    "Fatima",
    "Daniel",
    "Sofia",
    "Wei",
    "Mei",
    "Yusuf",
    "Aisha",
    "Marco",
    "Elena",
    "Kwame",
    "Amina",
    "Tariq",
    "Noor",
    "Ivan",
    "Clara",
]
LAST = [
    "Haddad",
    "Nair",
    "Okafor",
    "Petrov",
    "Khan",
    "Silva",
    "Moreau",
    "Tan",
    "Rahman",
    "Costa",
    "Farouk",
    "Iyer",
    "Novak",
    "Mansour",
    "Dubois",
    "Chen",
    "Bianchi",
    "Aziz",
    "Murray",
    "Hussain",
]
MIDDLE = ["Ali", "Maria", "Kumar", "Lee", "Noor", "James", "Anne", "Said"]
CITIES = ["Exampleton", "Samplebury", "Testville", "Mockford", "Placeholder Bay"]
STREETS = ["Imaginary Street", "Fictional Avenue", "Sample Road", "Testing Lane", "Mock Boulevard"]
BUILDINGS = ["Palm Court Tower", "Garden View Residence", "Harbour Heights", "Example Plaza"]
ISSUERS = [
    "Imaginary Power & Water Co.",
    "Fictional Telecom Ltd",
    "Sample Gas & Electric",
    "Mockford Municipal Services",
    "Testland Broadband",
]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

ID_COUNT, POA_COUNT = 10, 8
DEGRADED_IDS = {3, 6, 9}
DEGRADED_POA = {2, 5, 7}
PDF_POA = {5, 6, 7}


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def fmt_date(d: date, style: str) -> str:
    if style == "dmy_mon":  # 12 APR 1990
        return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"
    if style == "dmy_slash":  # only used when the day is above 12, so it is unambiguous
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    return f"{MONTH_NAMES[d.month - 1]} {d.day}, {d.year}"  # April 12, 1990


def pick_date_style(rng: random.Random, d: date) -> str:
    styles = ["dmy_mon", "long"] + (["dmy_slash"] if d.day > 12 else [])
    return rng.choice(styles)


def watermark(img: Image.Image, text: str = "SPECIMEN") -> Image.Image:
    base = img.convert("RGBA")
    layer = Image.new("RGBA", (base.width * 2, base.height * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    f = font(max(base.width // 9, 40))
    step = int(f.size * 2.6)
    for y in range(0, layer.height, step):
        for x in range(0, layer.width, int(f.size * 6.2)):
            draw.text((x + (y // step % 2) * f.size * 3, y), text, font=f, fill=(120, 120, 120, 46))
    layer = layer.rotate(28, resample=Image.BICUBIC)
    left, top = (layer.width - base.width) // 2, (layer.height - base.height) // 2
    layer = layer.crop((left, top, left + base.width, top + base.height))
    return Image.alpha_composite(base, layer).convert("RGB")


def degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    """Make a document harder to read: blur, small rotation, glare and low resolution."""
    out = img
    out = out.rotate(
        rng.choice([-5, -3, 3, 5]), resample=Image.BICUBIC, expand=True, fillcolor=(235, 235, 235)
    )
    out = out.filter(ImageFilter.GaussianBlur(rng.choice([1.2, 1.6, 2.0])))
    glare = Image.new("RGBA", out.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glare)
    w, h = out.size
    gd.ellipse((w * 0.45, h * 0.1, w * 0.95, h * 0.55), fill=(255, 255, 255, 120))
    out = Image.alpha_composite(out.convert("RGBA"), glare.filter(ImageFilter.GaussianBlur(40)))
    out = out.convert("RGB")
    return out.resize((int(w * 0.62), int(h * 0.62)), Image.BILINEAR)


def person(rng: random.Random) -> str:
    parts = [rng.choice(FIRST)]
    if rng.random() < 0.4:
        parts.append(rng.choice(MIDDLE))
    parts.append(rng.choice(LAST))
    return " ".join(parts)


def draw_photo(
    draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], background: tuple[int, int, int]
) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=(200, 205, 210), outline=(90, 90, 90), width=3)
    cx = (x0 + x1) // 2
    head = (x1 - x0) // 4
    draw.ellipse(
        (cx - head, y0 + (y1 - y0) // 6, cx + head, y0 + (y1 - y0) // 6 + head * 2),
        fill=(150, 155, 160),
    )
    draw.ellipse(
        (cx - head * 2, y0 + (y1 - y0) // 2, cx + head * 2, y1 + head * 2), fill=(150, 155, 160)
    )
    draw.rectangle((x0, y1 + 3, x1, y1 + head * 3), fill=background)  # trim the shoulders


def make_id(rng: random.Random, index: int) -> tuple[Image.Image, dict[str, str]]:
    name = person(rng).upper()
    dob = date(rng.randint(1960, 2003), rng.randint(1, 12), rng.randint(1, 28))
    issued = TODAY - timedelta(days=rng.randint(60, 1500))
    expiry = date(issued.year + 10, issued.month, issued.day)
    number = f"SPC{rng.randint(1000000, 9999999)}{rng.choice('ABCDEFGH')}"
    labels = {
        "full_name": name,
        "date_of_birth": dob.isoformat(),
        "id_number": number,
        "nationality": "EXAMPLIAN",
        "expiry_date": expiry.isoformat(),
        "issuing_country": "REPUBLIC OF EXAMPLIA",
    }
    style = pick_date_style(rng, dob)
    shown = {
        "dob": fmt_date(dob, style),
        "expiry": fmt_date(expiry, style if expiry.day > 12 or style != "dmy_slash" else "dmy_mon"),
    }

    w, h = 1011, 638
    template_b = index % 2 == 1
    card = (238, 230, 205) if not template_b else (214, 228, 238)
    img = Image.new("RGB", (w, h), card)
    d = ImageDraw.Draw(img)
    head_fill = (32, 70, 120) if not template_b else (60, 60, 70)
    d.rectangle((0, 0, w, 92), fill=head_fill)
    d.text((32, 22), "REPUBLIC OF EXAMPLIA", font=font(38), fill=(255, 255, 255))
    d.text((32, 64), "NATIONAL IDENTITY CARD  -  SPECIMEN", font=font(20), fill=(220, 225, 235))
    d.rectangle((6, 6, w - 6, h - 6), outline=head_fill, width=4)

    photo = (40, 130, 280, 420) if not template_b else (w - 300, 130, w - 60, 420)
    draw_photo(d, photo, card)
    left = 320 if not template_b else 48
    lab, val = font(19), font(31)
    rows = [
        ("NAME", name),
        ("DATE OF BIRTH", shown["dob"]),
        ("ID NUMBER", number),
        ("NATIONALITY", "EXAMPLIAN"),
        ("DATE OF EXPIRY", shown["expiry"]),
    ]
    y = 118
    for label, value in rows:
        d.text((left, y), label, font=lab, fill=(80, 80, 90))
        d.text((left, y + 22), value, font=val, fill=(15, 15, 20))
        y += 74
    d.text((left, h - 70), "ISSUED BY: REPUBLIC OF EXAMPLIA", font=font(22), fill=(60, 60, 70))
    return img, labels


def make_poa(rng: random.Random, index: int) -> tuple[Image.Image, dict[str, str]]:
    name = person(rng).title()
    address = (
        f"{rng.choice(['Flat', 'Unit', 'Apartment'])} {rng.randint(1, 40)}{rng.choice('0123')}"
        f"{rng.randint(0, 9)}, {rng.choice(BUILDINGS)}, {rng.choice(STREETS)} {rng.randint(1, 99)}"
    )
    city = rng.choice(CITIES)
    issuer = rng.choice(ISSUERS)
    issued = TODAY - timedelta(days=rng.randint(5, 80))
    style = pick_date_style(rng, issued)
    labels = {
        "full_name": name,
        "address_line": address,
        "city": city,
        "issue_date": issued.isoformat(),
        "issuer": issuer,
    }

    w, h = 1240, 1754
    bank_style = index % 2 == 1
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    band = (0, 120, 90) if not bank_style else (70, 70, 80)
    d.rectangle((0, 0, w, 170), fill=band)
    d.text((70, 52), issuer, font=font(54), fill=(255, 255, 255))
    title = "UTILITY BILL" if not bank_style else "ACCOUNT STATEMENT"
    d.text((70, 215), title + "  -  SPECIMEN", font=font(40), fill=(40, 40, 40))

    d.text((70, 330), "Customer", font=font(24), fill=(110, 110, 110))
    d.text((70, 362), name, font=font(40), fill=(10, 10, 10))
    d.text((70, 424), address, font=font(30), fill=(20, 20, 20))
    d.text((70, 466), city, font=font(30), fill=(20, 20, 20))

    d.text(
        (760, 330),
        "Statement date" if bank_style else "Bill date",
        font=font(24),
        fill=(110, 110, 110),
    )
    d.text(
        (760, 362),
        fmt_date(issued, style).title() if style != "dmy_slash" else fmt_date(issued, style),
        font=font(34),
        fill=(10, 10, 10),
    )
    d.text(
        (760, 424),
        f"Account no. {rng.randint(10000000, 99999999)}",
        font=font(26),
        fill=(60, 60, 60),
    )

    y = 640
    d.line((70, y - 20, w - 70, y - 20), fill=(180, 180, 180), width=3)
    for item in ("Usage charge", "Service fee", "Taxes", "Previous balance"):
        d.text((70, y), item, font=font(30), fill=(40, 40, 40))
        d.text(
            (w - 330, y),
            f"{rng.randint(20, 480)}.{rng.randint(0, 99):02d}",
            font=font(30),
            fill=(40, 40, 40),
        )
        y += 70
    d.line((70, y, w - 70, y), fill=(180, 180, 180), width=3)
    d.text((70, y + 30), "Total due", font=font(38), fill=(10, 10, 10))
    d.text(
        (w - 330, y + 30),
        f"{rng.randint(300, 1900)}.{rng.randint(0, 99):02d}",
        font=font(38),
        fill=(10, 10, 10),
    )
    d.text(
        (70, h - 130),
        "This is a synthetic specimen document created for software testing.",
        font=font(24),
        fill=(130, 130, 130),
    )
    return img, labels


def generate(out: Path) -> dict:
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)
    documents = []

    for i in range(ID_COUNT):
        img, labels = make_id(rng, i)
        img = watermark(img)
        difficulty = "degraded" if i in DEGRADED_IDS else "clean"
        if difficulty == "degraded":
            img = degrade(img, rng)
        name = f"id_{i + 1:02d}." + ("jpg" if difficulty == "degraded" else "png")
        if name.endswith("jpg"):
            img.save(out / name, quality=38)
        else:
            img.save(out / name)
        documents.append(
            {
                "file": name,
                "document_type": "id_document",
                "difficulty": difficulty,
                "fields": labels,
            }
        )

    for i in range(POA_COUNT):
        img, labels = make_poa(rng, i)
        img = watermark(img)
        difficulty = "degraded" if i in DEGRADED_POA else "clean"
        if difficulty == "degraded":
            img = degrade(img, rng)
        name = f"poa_{i + 1:02d}." + ("pdf" if i in PDF_POA else "png")
        if name.endswith("pdf"):
            img.convert("RGB").save(out / name, "PDF", resolution=150)
        else:
            img.save(out / name)
        documents.append(
            {
                "file": name,
                "document_type": "proof_of_address",
                "difficulty": difficulty,
                "fields": labels,
            }
        )

    manifest = {
        "note": "Synthetic, fictional, watermarked SPECIMEN documents for testing only.",
        "seed": SEED,
        "documents": documents,
    }
    (out / "labels.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "golden")
    args = parser.parse_args()
    manifest = generate(args.out)
    print(f"wrote {len(manifest['documents'])} documents to {args.out}")


if __name__ == "__main__":
    main()
