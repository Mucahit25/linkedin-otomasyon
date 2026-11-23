from __future__ import annotations

import json
from datetime import timedelta

from conftest import PAZARTESI, gorsel_yaz

from kayit import Kayit
from yayinci.temel import PAYLASILDI, YayinciHatasi


def _kayit(ortam) -> Kayit:
    return Kayit(ortam["kok"] / ortam["ayar"]["klasorler"]["kayit"])


def test_proje_yokken_hicbir_sey_yapilmaz_ve_bitti_bildirimi_bir_kez(ortam, calistir):
    kod, b1 = calistir()
    assert kod == 0
    assert calistir.yayinci.olusturma_sayisi == 0
    assert any("Renderlar bitti" in k for k in b1.gonderilen)
    _, b2 = calistir(PAZARTESI + timedelta(days=1))
    assert not any("Renderlar bitti" in k for k in b2.gonderilen)
    assert calistir.yayinci.olusturma_sayisi == 0


def test_ayni_proje_iki_kez_gonderilmez(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "a.jpg", (10, 10, 10))
    gorsel_yaz(r / "b.jpg", (20, 20, 20))
    kod, _ = calistir()
    assert kod == 0
    assert calistir.yayinci.olusturma_sayisi == 2   # Pazartesi ve Çarşamba dilimleri
    for gun in range(1, 15):
        calistir(PAZARTESI + timedelta(days=gun))
    assert calistir.yayinci.olusturma_sayisi == 2
    idler = [p["proje_id"] for p in _kayit(ortam).projeler]
    assert len(idler) == len(set(idler)) == 2


def test_dosya_adi_degisse_de_tekrar_paylasilmaz(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "a.jpg", (10, 10, 10))
    calistir()
    (r / "a.jpg").rename(r / "yeni-ad.jpg")
    calistir(PAZARTESI + timedelta(days=7))
    assert calistir.yayinci.olusturma_sayisi == 1


def test_paylasilmis_gorseli_iceren_yeni_klasor_atlanir_ve_uyarilir(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "proje" / "01.jpg", (10, 10, 10))
    calistir()
    gorsel_yaz(r / "proje" / "02.jpg", (30, 30, 30))   # paylaşılmış klasöre ekleme
    _, b = calistir(PAZARTESI + timedelta(days=7))
    assert calistir.yayinci.olusturma_sayisi == 1
    assert any("uyarı" in k.lower() for k in b.gonderilen)


def test_yeni_render_gelince_devam_eder(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    calistir()
    assert _kayit(ortam).bayrak("bitti_bildirimi_gonderildi")
    gorsel_yaz(r / "yeni.jpg")
    calistir(PAZARTESI + timedelta(hours=1))
    assert calistir.yayinci.olusturma_sayisi == 1
    assert not _kayit(ortam).bayrak("bitti_bildirimi_gonderildi")


def test_haftada_en_fazla_adet_ve_ufuk(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    for i in range(6):
        gorsel_yaz(r / f"r{i}.jpg", (i * 30, 0, 0))
    calistir()
    # Pazartesi 09:00 (3 saatten az kaldı, atlanır), 7 günlük ufuk: Salı-Cuma = 4,
    # artı gelecek Pazartesi 09:00 = 5. Render 6 olsa da ufuk dışı planlanmaz.
    assert calistir.yayinci.olusturma_sayisi == 5


def test_yarim_kalan_kayit_yeniden_gonderilmez(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "a.jpg")
    calistir.yayinci.hata_ver = YayinciHatasi("bağlantı koptu", kesin=False)
    kod, _ = calistir()
    assert kod == 1
    assert _kayit(ortam).projeler[0]["durum"] == "gonderiliyor"
    calistir.yayinci.hata_ver = None
    kod, b = calistir(PAZARTESI + timedelta(days=7))
    assert calistir.yayinci.olusturma_sayisi == 0
    assert _kayit(ortam).projeler[0]["durum"] == "hata"
    assert any("yarıda" in k for k in b.gonderilen)


def test_kesin_reddedilen_gonderi_sonra_yeniden_denenir(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "a.jpg")
    calistir.yayinci.hata_ver = YayinciHatasi("reddedildi", kesin=True)
    calistir()
    assert _kayit(ortam).projeler == []
    calistir.yayinci.hata_ver = None
    calistir(PAZARTESI + timedelta(hours=1))
    assert calistir.yayinci.olusturma_sayisi == 1


def test_paylasilinca_durum_guncellenir(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "a.jpg")
    calistir()
    for g in calistir.yayinci.gonderiler.values():
        g.durum = PAYLASILDI
    calistir(PAZARTESI + timedelta(days=2))
    assert _kayit(ortam).projeler[0]["durum"] == "paylasildi"


def test_deneme_modu_kayda_ve_buffera_dokunmaz(ortam, calistir):
    r = ortam["kok"] / "renderlar"
    gorsel_yaz(r / "a.jpg")
    kod, b = calistir(deneme=True)
    assert kod == 0
    assert calistir.yayinci.olusturma_sayisi == 0
    assert not (ortam["kok"] / "kayit" / "paylasimlar.json").exists()
    assert calistir.depo.commitler == []
    assert any("DENEME" in k for k in b.gonderilen)


def test_kapaliyken_hicbir_sey_yapmaz(ortam, calistir):
    ortam["ayar"]["aktif"] = False
    gorsel_yaz(ortam["kok"] / "renderlar" / "a.jpg")
    calistir()
    assert calistir.yayinci.olusturma_sayisi == 0


def test_en_fazla_siniri(ortam, calistir):
    import main
    from bildirim import Bildirici
    from conftest import sahte_aciklama
    for i in range(3):
        gorsel_yaz(ortam["kok"] / "renderlar" / f"r{i}.jpg", (i * 50, 0, 0))
    main.calistir(simdi=PAZARTESI, kok=ortam["kok"], ayar=ortam["ayar"],
                  yayinci=calistir.yayinci, depo=calistir.depo, aciklama_fn=sahte_aciklama,
                  bildirici=Bildirici(ortam["ayar"]), en_fazla=1)
    assert calistir.yayinci.olusturma_sayisi == 1


def test_ayni_gonderi_kayit_ve_bufferda_iki_kez_sayilmaz(ortam, calistir):
    """Gerçek hata (2026-11-22): kayıttaki gönderi Buffer listesinde de göründüğü için haftaya
    iki kez sayıldı, haftalık sınır erken doldu ve Cuma boş kaldı."""
    import main
    from bildirim import Bildirici
    from conftest import sahte_aciklama
    for i in range(7):
        gorsel_yaz(ortam["kok"] / "renderlar" / f"r{i}.jpg", (i * 35, 0, 0))

    def tur(simdi, en_fazla=0):
        main.calistir(simdi=simdi, kok=ortam["kok"], ayar=ortam["ayar"],
                      yayinci=calistir.yayinci, depo=calistir.depo, aciklama_fn=sahte_aciklama,
                      bildirici=Bildirici(ortam["ayar"]), en_fazla=en_fazla)

    tur(PAZARTESI - timedelta(hours=12), en_fazla=1)   # Pazar akşamı: sadece Pazartesi
    tur(PAZARTESI - timedelta(hours=11))               # sınırsız: Salı-Cuma da dolmalı
    assert calistir.yayinci.olusturma_sayisi == 5      # haftalık sınır 5, iki kez sayılmaz


def test_kayit_dosyasi_gecerli_json(ortam, calistir):
    gorsel_yaz(ortam["kok"] / "renderlar" / "a.jpg")
    calistir()
    veri = json.loads((ortam["kok"] / "kayit" / "paylasimlar.json").read_text(encoding="utf-8"))
    p = veri["projeler"][0]
    assert p["durum"] == "taslak" and p["buffer_post_id"] == "p1"
    assert len(p["etiketler"]) == 5
