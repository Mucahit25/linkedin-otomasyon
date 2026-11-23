"""Paylaşım zaman dilimleri.

- Dilimler config.yaml'dan gelir (gün + başlangıç/bitiş saati), saat dilimi Europe/Istanbul.
- Sadece önümüzdeki `planlama_ufku_gun` gün doldurulur.
- Başlangıcına `min_sure_saat`ten az kalan dilim atlanır.
- O gün takvimde zaten bir gönderi varsa (kayıttan ya da Buffer'dan, elle eklenenler dahil)
  dilim dolu sayılır.
- Bir haftada (Pzt-Paz) `haftalik_adet` kadar gönderi varsa o haftanın kalan dilimleri atlanır.
- Gönderi dilim içinde rastgele bir dakikaya konur; rastgelelik proje kimliğiyle tohumlanır,
  yeniden çalışmada aynı dakika çıkar.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

GUNLER = {"pazartesi": 0, "sali": 1, "carsamba": 2, "persembe": 3,
          "cuma": 4, "cumartesi": 5, "pazar": 6}
GUN_ADLARI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AY_ADLARI = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


@dataclass(frozen=True)
class Dilim:
    bas: datetime
    bit: datetime


def _saat(metin: str) -> time:
    s, d = metin.split(":")
    return time(int(s), int(d))


def _hafta(gun: date) -> tuple[int, int]:
    yil, hafta, _ = gun.isocalendar()
    return yil, hafta


def dilimleri_uret(simdi: datetime, ayar: dict) -> list[Dilim]:
    tz = ZoneInfo(ayar["saat_dilimi"])
    simdi = simdi.astimezone(tz)
    ufuk = simdi + timedelta(days=int(ayar.get("planlama_ufku_gun", 7)))
    en_erken = simdi + timedelta(hours=float(ayar.get("min_sure_saat", 3)))
    dilimler = []
    for gun_farki in range(int(ayar.get("planlama_ufku_gun", 7)) + 1):
        gun = simdi.date() + timedelta(days=gun_farki)
        for z in ayar["zaman_dilimleri"]:
            if GUNLER[z["gun"]] != gun.weekday():
                continue
            bas = datetime.combine(gun, _saat(z["bas"]), tz)
            bit = datetime.combine(gun, _saat(z["bit"]), tz)
            if bas >= en_erken and bas <= ufuk:
                dilimler.append(Dilim(bas, bit))
    return sorted(dilimler, key=lambda d: d.bas)


def bos_dilimler(simdi: datetime, ayar: dict, dolu: list[datetime]) -> list[Dilim]:
    tz = ZoneInfo(ayar["saat_dilimi"])
    dolu_yerel = [z.astimezone(tz) for z in dolu]
    dolu_gunler = {z.date() for z in dolu_yerel}
    haftalik: dict[tuple[int, int], int] = {}
    for z in dolu_yerel:
        haftalik[_hafta(z.date())] = haftalik.get(_hafta(z.date()), 0) + 1
    sinir = int(ayar.get("haftalik_adet", 3))
    bos = []
    for d in dilimleri_uret(simdi, ayar):
        gun = d.bas.date()
        if gun in dolu_gunler or haftalik.get(_hafta(gun), 0) >= sinir:
            continue
        bos.append(d)
        # Bu dilim doldurulacak varsayılır: aynı haftanın sayacına eklenir.
        haftalik[_hafta(gun)] = haftalik.get(_hafta(gun), 0) + 1
        dolu_gunler.add(gun)
    return bos


def dakika_sec(dilim: Dilim, tohum: str) -> datetime:
    dakika = max(1, int((dilim.bit - dilim.bas).total_seconds() // 60))
    return dilim.bas + timedelta(minutes=random.Random(tohum).randrange(dakika))


def okunur(zaman: datetime, saat_dilimi: str = "Europe/Istanbul") -> str:
    z = zaman.astimezone(ZoneInfo(saat_dilimi))
    return f"{z.day} {AY_ADLARI[z.month - 1]} {GUN_ADLARI[z.weekday()]}, saat {z:%H:%M}"
