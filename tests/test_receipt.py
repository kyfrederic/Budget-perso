"""Extraction du total, de la date et du commerçant dans le texte d'un ticket."""
import io
from datetime import date

import pytest

from budget import receipt

JOUR = date(2026, 11, 15)


def lire(texte):
    return receipt.extract(texte, today=JOUR)


def test_total_ttc_plutot_que_sous_total_ou_tva():
    r = lire("LE BISTROT DU MARCHE\n14/11/2026 20:47\n2 MENU 48,00\nSOUS-TOTAL 62,00\nTVA 10% 5,64\nTOTAL TTC 62,00\nCB 62,00")
    assert (r.amount, r.bought_on, r.label) == (6200, "2026-11-14", "Le Bistrot Du Marche")


def test_total_a_payer_et_date_courte():
    r = lire("CARREFOUR MARKET\nLAIT 5,94\nNOMBRE D'ARTICLES 7\nTOTAL A PAYER 42,23\nCARTE BANCAIRE 42,23\n13/11/26 18:02")
    assert (r.amount, r.bought_on) == (4223, "2026-11-13")


def test_remise_ignoree_et_milliers():
    assert lire("PERCEUSE 129,00\nRemise fidelite -5,00\nTOTAL 1 245,40\ndont TVA 20% 207,57").amount == 124540


def test_montant_sur_la_ligne_suivante():
    assert lire("NET A PAYER\n   18,90 EUR").amount == 1890


def test_sans_mot_cle_le_plus_grand_montant():
    assert lire("CAFE 2,50\nCROISSANT 1,30\n3,80").amount == 380


def test_rien_de_lisible():
    r = lire("~~ ## ..\n")
    assert r.amount is None and r.bought_on is None


def test_date_impossible_ou_future_ecartee():
    assert lire("TOTAL 5,00\n31/02/2026").bought_on is None
    assert lire("TOTAL 5,00\n01/12/2031").bought_on is None


def test_fichier_refuse():
    with pytest.raises(receipt.ReceiptError):
        receipt.prepare(b"%PDF-1.4 pas une image")
    with pytest.raises(receipt.ReceiptError):
        receipt.prepare(b"x" * (receipt.MAX_BYTES + 1))


def test_photo_reencodee_sans_metadonnees(tmp_path):
    from PIL import Image
    src = Image.new("RGB", (3000, 2000), "white")
    exif = Image.Exif()
    exif[0x010F] = "Appareil"                       # une métadonnée quelconque
    buf = io.BytesIO()
    src.save(buf, "JPEG", exif=exif)
    token = receipt.save(receipt.prepare(buf.getvalue()), tmp_path)
    out = Image.open(receipt.photo_path(tmp_path, token))
    assert max(out.size) == receipt.MAX_SIDE and not out.getexif()
    assert receipt.photo_path(tmp_path, "../" + token) is None
