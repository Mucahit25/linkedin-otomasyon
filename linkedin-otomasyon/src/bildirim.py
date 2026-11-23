"""Bildirimler: e-posta (Gmail, uygulama şifresiyle) ve isteğe bağlı WhatsApp (CallMeBot).

Bildirim hatası asla akışı durdurmaz: sadece ekrana (GitHub çalışma günlüğüne) yazılır.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests

KONU_ON_EKI = "[LinkedIn]"


class Bildirici:
    def __init__(self, ayar: dict, deneme: bool = False):
        self.ayar = ayar.get("bildirim", {}) or {}
        self.deneme = deneme
        self.gonderilen: list[str] = []  # testler ve özet için

    def gonder(self, konu: str, metin: str, ekler: list[Path] | None = None) -> bool:
        if self.deneme:
            konu = f"DENEME · {konu}"
        tam_konu = f"{KONU_ON_EKI} {konu}"
        print(f"\n=== BİLDİRİM: {tam_konu} ===\n{metin}\n")
        self.gonderilen.append(tam_konu)
        basarili = False
        if self.ayar.get("eposta", True):
            basarili = self._eposta(tam_konu, metin, ekler or [])
        if self.ayar.get("whatsapp"):
            self._whatsapp(f"{tam_konu}\n{metin}")
        return basarili

    def _eposta(self, konu: str, metin: str, ekler: list[Path]) -> bool:
        adres = os.environ.get("GMAIL_ADRES", "")
        sifre = os.environ.get("GMAIL_UYGULAMA_SIFRESI", "").replace(" ", "")
        alici = os.environ.get("BILDIRIM_EPOSTA") or adres
        if not (adres and sifre):
            print("(E-posta bilgisi yok, mail gönderilmedi.)")
            return False
        mesaj = EmailMessage()
        mesaj["Subject"] = konu
        mesaj["From"] = adres
        mesaj["To"] = alici
        mesaj.set_content(metin)
        for ek in ekler:
            try:
                mesaj.add_attachment(Path(ek).read_bytes(), maintype="image", subtype="jpeg",
                                     filename=Path(ek).name)
            except OSError as e:
                print(f"(Ek eklenemedi: {ek}: {e})")
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
                smtp.login(adres, sifre)
                smtp.send_message(mesaj)
            return True
        except Exception as e:  # noqa: BLE001 - bildirim akışı asla durdurmaz
            print(f"(E-posta gönderilemedi: {type(e).__name__}: {e})")
            return False

    def _whatsapp(self, metin: str) -> None:
        telefon = os.environ.get("WHATSAPP_TELEFON", "")
        anahtar = os.environ.get("WHATSAPP_APIKEY", "")
        if not (telefon and anahtar):
            return
        try:
            requests.get("https://api.callmebot.com/whatsapp.php",
                         params={"phone": telefon, "text": metin[:1500], "apikey": anahtar},
                         timeout=30)
        except requests.RequestException as e:
            print(f"(WhatsApp gönderilemedi: {e})")
