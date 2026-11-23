"""Kalıcı paylaşım kaydı (kayit/paylasimlar.json).

Kural: kayda bir kez giren proje (durumu ne olursa olsun) bir daha asla paylaşılmaz.
Kayda girme anı, Buffer'a gönderimden HEMEN ÖNCE ('gonderiliyor' durumu) olur; böylece
çalışma yarıda kesilse bile aynı proje ikinci kez gönderilmez.

Durumlar:
  gonderiliyor  Buffer'a gönderilmek üzere; sonucu henüz bilinmiyor
  taslak        Buffer'da taslak (onay modu)
  planlandi     Buffer'da planlı
  paylasildi    LinkedIn'de yayında
  silindi       Buffer'dan elle silinmiş (yine de bir daha paylaşılmaz)
  hata          Buffer gönderiyi yayınlayamadı ya da sonucu doğrulanamadı
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

ACIK_DURUMLAR = ("gonderiliyor", "taslak", "planlandi")
TAKVIMDE_YER_TUTAN = ("gonderiliyor", "taslak", "planlandi", "paylasildi")

_BOS = {
    "surum": 1,
    "bitti_bildirimi_gonderildi": False,
    "logo_uyarisi_gonderildi": False,
    "gonderilen_uyarilar": [],
    "projeler": [],
}


class Kayit:
    def __init__(self, yol: Path):
        self.yol = Path(yol)
        if self.yol.is_file():
            self.veri = json.loads(self.yol.read_text(encoding="utf-8"))
        else:
            self.veri = json.loads(json.dumps(_BOS))
        for anahtar, deger in _BOS.items():
            self.veri.setdefault(anahtar, json.loads(json.dumps(deger)))
        self.degisti = False

    # --- okuma ---
    @property
    def projeler(self) -> list[dict]:
        return self.veri["projeler"]

    def proje(self, proje_id: str) -> dict | None:
        return next((p for p in self.projeler if p["proje_id"] == proje_id), None)

    def kullanilmis_mi(self, proje_id: str) -> bool:
        return self.proje(proje_id) is not None

    def kullanilan_hashler(self) -> set[str]:
        return {g["hash"] for p in self.projeler for g in p.get("gorseller", [])}

    def onceki_aciklamalar(self, adet: int = 10) -> list[str]:
        sirali = sorted((p for p in self.projeler if p.get("aciklama")),
                        key=lambda p: p.get("olusturma", ""))
        return [p["aciklama"] for p in sirali][-adet:]

    def gecmis_etiketler(self) -> list[list[str]]:
        sirali = sorted((p for p in self.projeler if p.get("etiketler")),
                        key=lambda p: p.get("olusturma", ""))
        return [p["etiketler"] for p in sirali]

    def takvim_kayitlari(self) -> dict[str, datetime]:
        """Takvimde yer tutan gönderiler: {anahtar: planlanan zaman}. Anahtar Buffer gönderi
        kimliğidir (yoksa proje kimliği); böylece Buffer'dan gelen aynı gönderi iki kez sayılmaz."""
        kayitlar = {}
        for p in self.projeler:
            if p.get("durum") in TAKVIMDE_YER_TUTAN and p.get("planlanan"):
                anahtar = p.get("buffer_post_id") or f"proje:{p['proje_id']}"
                kayitlar[anahtar] = datetime.fromisoformat(p["planlanan"])
        return kayitlar

    def takvim_zamanlari(self) -> list[datetime]:
        return list(self.takvim_kayitlari().values())

    # --- yazma ---
    def ekle(self, proje: dict) -> None:
        if self.kullanilmis_mi(proje["proje_id"]):
            raise ValueError(f"Proje zaten kayıtta: {proje['proje_id']}")
        self.projeler.append(proje)
        self.degisti = True

    def guncelle(self, proje_id: str, **alanlar) -> None:
        p = self.proje(proje_id)
        if p is None:
            raise KeyError(proje_id)
        for k, v in alanlar.items():
            if p.get(k) != v:
                p[k] = v
                self.degisti = True

    def sil(self, proje_id: str) -> None:
        """Sadece Buffer'ın gönderiyi kesin olarak reddettiği durumda kullanılır."""
        once = len(self.projeler)
        self.veri["projeler"] = [p for p in self.projeler if p["proje_id"] != proje_id]
        self.degisti = self.degisti or len(self.projeler) != once

    def bayrak(self, ad: str) -> bool:
        return bool(self.veri.get(ad))

    def bayrak_yaz(self, ad: str, deger: bool) -> None:
        if bool(self.veri.get(ad)) != deger:
            self.veri[ad] = deger
            self.degisti = True

    def uyari_gonderildi_mi(self, anahtar: str) -> bool:
        return anahtar in self.veri["gonderilen_uyarilar"]

    def uyari_isaretle(self, anahtar: str) -> None:
        if anahtar not in self.veri["gonderilen_uyarilar"]:
            self.veri["gonderilen_uyarilar"].append(anahtar)
            self.degisti = True

    def kaydet(self) -> None:
        """Geçici dosyaya yazıp yerine koyar: yarıda kesilirse eski kayıt bozulmaz."""
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        metin = json.dumps(self.veri, ensure_ascii=False, indent=2) + "\n"
        fd, gecici = tempfile.mkstemp(dir=self.yol.parent, prefix=".kayit_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(metin)
            os.replace(gecici, self.yol)
        except BaseException:
            Path(gecici).unlink(missing_ok=True)
            raise
        self.degisti = False
