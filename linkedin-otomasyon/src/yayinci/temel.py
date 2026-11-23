"""Yayıncı arayüzü. Bugün Buffer; ileride LinkedIn'in kendi yolu ya da başka bir
servis aynı arayüzle eklenebilir (main.py değişmez)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

# Ortak durum adları (kayit.py ile aynı dil)
TASLAK, PLANLANDI, GONDERILIYOR, PAYLASILDI, HATA, ONAY_BEKLIYOR = (
    "taslak", "planlandi", "gonderiliyor", "paylasildi", "hata", "onay_bekliyor")


class YayinciHatasi(Exception):
    """kesin=True: servis gönderiyi kesin olarak reddetti (hiçbir şey oluşmadı).
    kesin=False: sonucu bilinmiyor (bağlantı koptu vb.), gönderi oluşmuş olabilir."""

    def __init__(self, mesaj: str, kesin: bool = True):
        super().__init__(mesaj)
        self.kesin = kesin


@dataclass
class Gonderi:
    id: str
    durum: str               # yukarıdaki ortak durum adlarından biri
    zaman: datetime | None   # planlanan ya da paylaşılan zaman
    metin: str = ""


class Yayinci(ABC):
    @abstractmethod
    def gonderi_olustur(self, metin: str, gorsel_urlleri: list[str], zaman: datetime,
                        taslak: bool) -> Gonderi: ...

    @abstractmethod
    def planli_gonderileri_getir(self) -> list[Gonderi]:
        """Takvimde yer tutan gönderiler: taslak, planlı, gönderiliyor ve son paylaşılanlar."""

    @abstractmethod
    def durum_sorgula(self, gonderi_id: str) -> Gonderi | None:
        """Gönderi silinmişse None."""

    @abstractmethod
    def gonderi_sil(self, gonderi_id: str) -> None: ...

    def panel_linki(self) -> str:
        return ""
