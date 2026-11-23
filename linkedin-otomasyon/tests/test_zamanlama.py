from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from conftest import PAZARTESI

from zamanlama import bos_dilimler, dakika_sec, dilimleri_uret, okunur

IST = ZoneInfo("Europe/Istanbul")
AYAR = {
    "saat_dilimi": "Europe/Istanbul",
    "zaman_dilimleri": [{"gun": "sali", "bas": "19:00", "bit": "20:00"},
                        {"gun": "carsamba", "bas": "18:00", "bit": "19:00"},
                        {"gun": "persembe", "bas": "10:00", "bit": "11:00"}],
    "planlama_ufku_gun": 7, "min_sure_saat": 3, "haftalik_adet": 3,
}


def test_yedi_gun_icindeki_dilimler():
    d = dilimleri_uret(PAZARTESI, AYAR)
    assert [x.bas.strftime("%a %H:%M") for x in d] == ["Tue 19:00", "Wed 18:00", "Thu 10:00"]


def test_uc_saatten_az_kalan_dilim_atlanir():
    sali_1700 = datetime(2026, 11, 24, 17, 0, tzinfo=IST)
    d = dilimleri_uret(sali_1700, AYAR)
    assert d[0].bas.date().isoformat() == "2026-11-25"
    sali_1500 = datetime(2026, 11, 24, 15, 59, tzinfo=IST)
    assert dilimleri_uret(sali_1500, AYAR)[0].bas.date().isoformat() == "2026-11-24"


def test_dolu_gun_atlanir():
    elle = datetime(2026, 11, 24, 12, 0, tzinfo=IST)  # Salı, dilim dışında ama aynı gün
    bos = bos_dilimler(PAZARTESI, AYAR, [elle])
    assert [x.bas.date().isoformat() for x in bos] == ["2026-11-25", "2026-11-26"]


def test_haftalik_sinir():
    ayar = dict(AYAR, haftalik_adet=2)
    pazartesi_gonderisi = datetime(2026, 11, 23, 8, 0, tzinfo=IST)
    bos = bos_dilimler(PAZARTESI, ayar, [pazartesi_gonderisi])
    assert len(bos) == 1


def test_dakika_dilim_icinde_ve_tekrarlanabilir():
    d = dilimleri_uret(PAZARTESI, AYAR)[0]
    z1 = dakika_sec(d, "abc")
    assert d.bas <= z1 < d.bit
    assert z1 == dakika_sec(d, "abc")


def test_utc_donusumu():
    d = dilimleri_uret(PAZARTESI, AYAR)[0]
    assert d.bas.astimezone(timezone.utc).hour == 16   # İstanbul 19:00 = UTC 16:00
    assert "Salı" in okunur(d.bas + timedelta(minutes=5))
