"""Ayar ve gizli anahtar yükleme.

Bulutta (GitHub Actions) anahtarlar ortam değişkeni olarak gelir.
Yerelde sırayla şunlara bakılır: linkedin-otomasyon/.env, sonra üst klasörlerde
_knowledge/credentials/master.env (Antigravity düzeni). Var olan değer ezilmez.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parent.parent  # linkedin-otomasyon/


def _env_oku(yol: Path) -> None:
    for satir in yol.read_text(encoding="utf-8-sig").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        ad, deger = satir.split("=", 1)
        ad, deger = ad.strip(), deger.strip().strip('"').strip("'")
        if deger and not os.environ.get(ad):
            os.environ[ad] = deger


def anahtarlari_yukle(kok: Path = KOK) -> None:
    yerel = kok / ".env"
    if yerel.is_file():
        _env_oku(yerel)
    for ust in kok.parents:
        master = ust / "_knowledge" / "credentials" / "master.env"
        if master.is_file():
            _env_oku(master)
            break
    # master.env'de Gmail bilgisi SMTP_* adıyla durur
    if not os.environ.get("GMAIL_ADRES") and os.environ.get("SMTP_USER"):
        os.environ["GMAIL_ADRES"] = os.environ["SMTP_USER"]
    if not os.environ.get("GMAIL_UYGULAMA_SIFRESI") and os.environ.get("SMTP_APP_PASSWORD"):
        os.environ["GMAIL_UYGULAMA_SIFRESI"] = os.environ["SMTP_APP_PASSWORD"]


def ayarlari_yukle(kok: Path = KOK) -> dict:
    return yaml.safe_load((kok / "config.yaml").read_text(encoding="utf-8"))
