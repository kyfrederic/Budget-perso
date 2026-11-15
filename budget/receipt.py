"""Lecture d'un ticket de caisse pris en photo.

Tout se passe sur le serveur : Pillow prépare l'image, le programme Tesseract lit le texte.
Le résultat n'est qu'une proposition, toujours confirmée ou corrigée par Fred.
"""
from __future__ import annotations

import io
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1600
FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
TOKEN = re.compile(r"[0-9a-f]{32}")
OCR_TIMEOUT = 20

AMOUNT = re.compile(r"(?<![\d,.])(\d{1,3}(?:[ .]\d{3})+|\d{1,6})\s?[.,]\s?(\d{2})(?!\d)")
DATE = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
# Du plus sûr au moins sûr. Le premier mot-clé trouvé avec un montant l'emporte.
KEYWORDS = [
    r"net a payer", r"total a payer", r"a payer", r"total ttc", r"montant ttc", r"montant du", r"total eur",
    r"\btotal\b", r"\bttc\b", r"carte bancaire", r"\bcb\b", r"especes?",
]
NOT_TOTAL = re.compile(r"sous.?total|total ht|\bht\b|tva|remise|rendu|articles?|points|cagnotte")


@dataclass
class Reading:
    amount: int | None = None      # centimes
    bought_on: str | None = None   # AAAA-MM-JJ
    label: str | None = None
    text: str = ""
    available: bool = True         # False si Tesseract n'est pas installé


class ReceiptError(ValueError):
    pass


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return t.casefold()


def _amounts(line: str) -> list[int]:
    out = []
    for m in AMOUNT.finditer(line):
        euros = int(re.sub(r"[ .]", "", m.group(1)))
        out.append(euros * 100 + int(m.group(2)))
    return out


def extract(text: str, today: date | None = None) -> Reading:
    """Cherche le total, la date et le commerçant dans le texte lu sur le ticket."""
    r = Reading(text=text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    plain = [_plain(l) for l in lines]

    for kw in KEYWORDS:
        for i, pl in enumerate(plain):
            if not re.search(kw, pl) or NOT_TOTAL.search(pl):
                continue
            found = _amounts(lines[i]) or (_amounts(lines[i + 1]) if i + 1 < len(lines) else [])
            if found:
                r.amount = found[-1]
                break
        if r.amount is not None:
            break
    if r.amount is None:
        every = [a for i, l in enumerate(lines) if not NOT_TOTAL.search(plain[i]) for a in _amounts(l)]
        if every:
            r.amount = max(every)

    today = today or date.today()
    for m in DATE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            found = date(y, mo, d)
        except ValueError:
            continue
        if date(today.year - 2, 1, 1) <= found <= today:
            r.bought_on = found.isoformat()
            break

    for l in lines[:6]:
        letters = re.sub(r"[^A-Za-zÀ-ÿ' &-]", "", l).strip(" -&'")
        if len(letters) >= 3 and len(letters) >= len(l) * 0.6:
            r.label = re.sub(r"\s+", " ", letters).title()[:40]
            break
    return r


def prepare(data: bytes):
    """Vérifie que c'est une image et la remet d'aplomb. Renvoie une image Pillow en RVB."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(data) > MAX_BYTES:
        raise ReceiptError("Photo trop lourde (10 Mo au plus).")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in FORMATS:
            raise ReceiptError("Format non pris en charge : envoie une photo JPEG, PNG ou WebP.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ReceiptError("Ce fichier n'est pas une photo lisible.") from exc
    img = ImageOps.exif_transpose(img).convert("RGB")     # tient compte de l'orientation du téléphone
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return img


def save(img, folder: Path) -> str:
    """Enregistre la photo réencodée (sans métadonnées, donc sans localisation). Renvoie son jeton."""
    folder.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    img.save(folder / f"{token}.jpg", "JPEG", quality=80, optimize=True)
    return token


def photo_path(folder: Path, token: str | None) -> Path | None:
    if not token or not TOKEN.fullmatch(token):
        return None
    path = folder / f"{token}.jpg"
    return path if path.is_file() else None


def purge_orphans(folder: Path, used: set[str], max_age_hours: int = 24) -> int:
    """Supprime les photos envoyées mais jamais rattachées à un achat."""
    if not folder.is_dir():
        return 0
    limit, n = time.time() - max_age_hours * 3600, 0
    for f in folder.glob("*.jpg"):
        if f.stem not in used and f.stat().st_mtime < limit:
            f.unlink(missing_ok=True)
            n += 1
    return n


def ocr(img) -> Reading:
    """Lit le texte de l'image avec Tesseract, puis en extrait le total."""
    from PIL import ImageOps

    exe = shutil.which("tesseract")
    if exe is None:
        return Reading(available=False)
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    if gray.width < 1000:                                   # un petit ticket se lit mieux agrandi
        k = 1400 / gray.width
        gray = gray.resize((1400, int(gray.height * k)))
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        gray.save(tmp.name, "PNG")
        try:
            out = subprocess.run(
                [exe, tmp.name, "stdout", "-l", "fra", "--psm", "6"],
                capture_output=True, timeout=OCR_TIMEOUT, check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return Reading()
    if out.returncode != 0:
        return Reading()
    return extract(out.stdout.decode("utf-8", "replace"))
