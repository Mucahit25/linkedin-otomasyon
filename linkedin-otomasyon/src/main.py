"""LinkedIn otomatik paylaşım: her çalıştırmada bir tur.

Kullanım:
  python src/main.py            gerçek çalışma (GitHub Actions)
  python src/main.py --deneme   her şeyi yapar ama Buffer'a göndermez, kayda ve depoya
                                dokunmaz; önizleme maili "DENEME" etiketiyle gider

Tur:
  1. Kayıttaki açık gönderilerin Buffer durumunu güncelle (paylaşıldı / hata / silindi).
     Yarıda kalmış ('gonderiliyor') kayıt varsa Buffer'da eşini ara; ASLA yeniden gönderme.
  2. renderlar/ klasöründe paylaşılmamış projeleri bul.
  3. Önümüzdeki günlerdeki boş zaman dilimlerini bul.
  4. Her boş dilim için sıradaki proje: görsel hazırla, açıklama yaz, kayda 'gonderiliyor'
     yaz ve depoya gönder, görsel adresini doğrula, Buffer'a gönder, kaydı güncelle, bildir.
  5. Proje kalmadıysa hiçbir şey paylaşma; "renderlar bitti" bildirimi bir kez.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aciklama import AciklamaHatasi, aciklama_yaz  # noqa: E402
from bildirim import Bildirici  # noqa: E402
from depo import Depo, DepoHatasi, url_bekle  # noqa: E402
from gorsel import GorselHatasi, hazirla, logo_bul  # noqa: E402
from kayit import ACIK_DURUMLAR, Kayit  # noqa: E402
from ortam import KOK, anahtarlari_yukle, ayarlari_yukle  # noqa: E402
from tarayici import Proje, tara  # noqa: E402
from yayinci import YayinciHatasi, yayinci_olustur  # noqa: E402
from yayinci.temel import HATA, PAYLASILDI, PLANLANDI, TASLAK, Gonderi  # noqa: E402
from zamanlama import bos_dilimler, dakika_sec, okunur  # noqa: E402


class Tur:
    def __init__(self, deneme: bool, simdi: datetime, kok: Path, ayar: dict,
                 yayinci, depo, aciklama_fn, bildirici: Bildirici):
        self.deneme = deneme
        self.simdi = simdi
        self.kok = kok
        self.ayar = ayar
        self.yayinci = yayinci
        self.depo = depo
        self.aciklama_fn = aciklama_fn
        self.bildirici = bildirici
        self.kayit = Kayit(kok / ayar["klasorler"]["kayit"])
        self.saat_dilimi = ayar["paylasim"]["saat_dilimi"]
        self.taslak_modu = bool(ayar["paylasim"].get("onay_modu", True))
        self.hata_var = False
        self.yeni_gonderiler: list[str] = []
        self.en_fazla = 0  # 0 = sınırsız; bu turda en fazla kaç gönderi

    # --- yardımcılar ---
    def hata(self, konu: str, metin: str, anahtar: str | None = None) -> None:
        self.hata_var = True
        if anahtar and self.kayit.uyari_gonderildi_mi(anahtar):
            print(f"(Daha önce bildirildi: {konu})")
            return
        self.bildirici.gonder(konu, metin)
        if anahtar and not self.deneme:
            self.kayit.uyari_isaretle(anahtar)

    def kaydi_yaz(self, mesaj: str, ekstra: list[Path] | None = None) -> str | None:
        if self.deneme or not self.kayit.degisti and not ekstra:
            return None
        self.kayit.kaydet()
        if self.depo is None:
            return None
        return self.depo.kaydet_gonder([self.kayit.yol, *(ekstra or [])], mesaj)

    # --- 1. durum güncelleme ---
    def durumlari_guncelle(self) -> None:
        acik = [p for p in self.kayit.projeler if p.get("durum") in ACIK_DURUMLAR]
        if not acik or self.yayinci is None:
            return
        for p in acik:
            if not p.get("buffer_post_id"):
                continue
            g = self.yayinci.durum_sorgula(p["buffer_post_id"])
            if g is None:
                self.kayit.guncelle(p["proje_id"], durum="silindi")
            elif g.durum == PAYLASILDI:
                self.kayit.guncelle(p["proje_id"], durum="paylasildi",
                                    paylasilma=(g.zaman or self.simdi).isoformat())
            elif g.durum == HATA:
                self.kayit.guncelle(p["proje_id"], durum="hata")
                self.hata("Gönderi LinkedIn'e gidemedi",
                          f"'{p['ad']}' gönderisini Buffer LinkedIn'e gönderemedi.\n"
                          f"Buffer'a girip gönderiye bak: {self.yayinci.panel_linki()}\n"
                          "Bu proje otomatik olarak yeniden gönderilmeyecek.",
                          anahtar=f"buffer_hata:{p['proje_id']}")
            elif g.durum in (TASLAK, PLANLANDI):
                alanlar = {"durum": g.durum}
                if g.zaman and g.durum == PLANLANDI:
                    alanlar["planlanan"] = g.zaman.isoformat()
                self.kayit.guncelle(p["proje_id"], **alanlar)

        yarim = [p for p in self.kayit.projeler
                 if p.get("durum") == "gonderiliyor" and not p.get("buffer_post_id")]
        if yarim:
            buffer_gonderileri = self.yayinci.planli_gonderileri_getir()
            for p in yarim:
                es = next((g for g in buffer_gonderileri
                           if g.metin.strip() == (p.get("metin") or "").strip()), None)
                if es:
                    self.kayit.guncelle(p["proje_id"], buffer_post_id=es.id, durum=es.durum)
                else:
                    self.kayit.guncelle(p["proje_id"], durum="hata")
                    self.hata("Bir gönderi yarıda kaldı",
                              f"'{p['ad']}' Buffer'a gönderilirken çalışma yarıda kesildi ve "
                              "Buffer'da bulunamadı.\nÇift paylaşım olmasın diye sistem bunu "
                              "yeniden göndermeyecek.\nİstersen Buffer'a elle ekleyebilirsin: "
                              f"{self.yayinci.panel_linki()}",
                              anahtar=f"yarim:{p['proje_id']}")

    # --- 2-5 ---
    def calis(self) -> None:
        self.durumlari_guncelle()

        renderlar = self.kok / self.ayar["klasorler"]["renderlar"]
        sonuc = tara(renderlar, self.ayar, {p["proje_id"] for p in self.kayit.projeler},
                     self.kayit.kullanilan_hashler())
        self.uyarilari_gonder(sonuc.uyarilar)

        logo = logo_bul(self.kok / self.ayar["gorsel"]["logo"]["dosya"])
        if logo is None and not self.kayit.bayrak("logo_uyarisi_gonderildi"):
            self.bildirici.gonder("Logo bulunamadı",
                                  "Logo dosyası yok, görseller logosuz hazırlanacak.")
            if not self.deneme:
                self.kayit.bayrak_yaz("logo_uyarisi_gonderildi", True)

        if not sonuc.projeler:
            if not self.kayit.bayrak("bitti_bildirimi_gonderildi"):
                self.bildirici.gonder(
                    "Renderlar bitti",
                    "Paylaşılacak yeni render kalmadı. Sistem durdu, hiçbir şey paylaşmayacak.\n"
                    "Yeni render ekleyince kendiliğinden devam eder.")
                if not self.deneme:
                    self.kayit.bayrak_yaz("bitti_bildirimi_gonderildi", True)
            print("Paylaşılacak yeni proje yok.")
            return
        self.kayit.bayrak_yaz("bitti_bildirimi_gonderildi", False)

        # Aynı gönderi hem kayıtta hem Buffer'da görünür: Buffer kimliğiyle tekilleştir
        # (Buffer'daki güncel saat kazanır; kullanıcı saati Buffer'da değiştirmiş olabilir).
        dolu = self.kayit.takvim_kayitlari()
        if self.yayinci is not None:
            dolu.update({g.id: g.zaman for g in self.yayinci.planli_gonderileri_getir() if g.zaman})
        bos = bos_dilimler(self.simdi, self.ayar["paylasim"], list(dolu.values()))
        print(f"{len(sonuc.projeler)} yeni proje, {len(bos)} boş zaman dilimi.")

        projeler = list(sonuc.projeler)
        if self.en_fazla:
            bos = bos[: self.en_fazla]
        for dilim in bos:
            while projeler:
                proje = projeler.pop(0)
                if self.proje_gonder(proje, dakika_sec(dilim, proje.proje_id), logo):
                    break
            else:
                break

    def uyarilari_gonder(self, uyarilar: list[tuple[str, str]]) -> None:
        yeni = [(a, m) for a, m in uyarilar if not self.kayit.uyari_gonderildi_mi(a)]
        if not yeni:
            return
        self.bildirici.gonder("Renderlarla ilgili uyarı", "\n\n".join(m for _, m in yeni))
        if not self.deneme:
            for a, _ in yeni:
                self.kayit.uyari_isaretle(a)

    def proje_gonder(self, proje: Proje, zaman: datetime, logo: Path | None) -> bool:
        """Dilimi doldurduysa True. Görsel bozuksa False (sıradaki projeye geçilir).
        Açıklama ya da Buffer gibi genel bir sorunda turu durdurmak için hata fırlatır."""
        hazir_kok = self.kok / ("deneme_cikti" if self.deneme else self.ayar["klasorler"]["hazir"])
        hazir_klasor = hazir_kok / proje.proje_id
        try:
            hazir = hazirla(proje.gorseller, hazir_klasor, self.ayar["gorsel"], logo)
        except GorselHatasi as e:
            self.hata("Bir render hazırlanamadı",
                      f"'{proje.ad}' hazırlanamadı: {e}\nBu proje atlandı, dosyayı kontrol et.",
                      anahtar=f"gorsel:{proje.proje_id}")
            return False

        sonuc = self.aciklama_fn(hazir, proje.bilgi, self.kayit.onceki_aciklamalar(
            int(self.ayar["aciklama"].get("onceki_aciklama_sayisi", 10))),
            self.kayit.gecmis_etiketler(), self.ayar)

        if self.deneme:
            self.bildirici.gonder(
                f"Önizleme: {proje.ad}",
                self._onizleme_metni(proje, zaman, sonuc["metin"], "Deneme: Buffer'a gönderilmedi."),
                ekler=hazir[:3])
            self.yeni_gonderiler.append(proje.ad)
            return True

        # Kayda gir: bu andan sonra bu proje bir daha asla ele alınmaz.
        self.kayit.ekle({
            "proje_id": proje.proje_id,
            "ad": proje.ad,
            "tur": proje.tur,
            "gorseller": [{"ad": g.name, "hash": h} for g, h in zip(proje.gorseller, proje.hashler)],
            "durum": "gonderiliyor",
            "buffer_post_id": None,
            "planlanan": zaman.isoformat(),
            "olusturma": self.simdi.isoformat(),
            "aciklama": sonuc["aciklama"],
            "etiketler": sonuc["etiketler"],
            "metin": sonuc["metin"],
            "hazir": hazir_klasor.relative_to(self.kok).as_posix(),
        })
        sha = self.kaydi_yaz(f"linkedin: {proje.ad} hazırlandı [skip ci]", ekstra=[hazir_klasor])
        urller = [self.depo.ham_url(sha, h) for h in hazir]
        try:
            url_bekle(urller)
        except DepoHatasi:
            # Buffer'a hiçbir şey gitmedi: kayıttan çıkar, sonraki turda yeniden denenir.
            self.kayit.sil(proje.proje_id)
            self.kaydi_yaz(f"linkedin: {proje.ad} geri alındı [skip ci]")
            raise

        try:
            gonderi: Gonderi = self.yayinci.gonderi_olustur(sonuc["metin"], urller, zaman,
                                                            taslak=self.taslak_modu)
        except YayinciHatasi as e:
            if e.kesin:
                # Buffer hiçbir şey oluşturmadı: kayıttan çıkar, sonraki turda yeniden denenir.
                self.kayit.sil(proje.proje_id)
                self.kaydi_yaz(f"linkedin: {proje.ad} geri alındı [skip ci]")
            raise
        self.kayit.guncelle(proje.proje_id, buffer_post_id=gonderi.id,
                            durum=TASLAK if self.taslak_modu else PLANLANDI)
        self.kaydi_yaz(f"linkedin: {proje.ad} {'taslak' if self.taslak_modu else 'planlandı'} [skip ci]")

        baslik = (f"Taslak hazır, onayını bekliyor: {proje.ad}" if self.taslak_modu
                  else f"Planlandı: {proje.ad}")
        self.bildirici.gonder(baslik, self._onizleme_metni(proje, zaman, sonuc["metin"]),
                              ekler=hazir[:3])
        self.yeni_gonderiler.append(proje.ad)
        return True

    def _onizleme_metni(self, proje: Proje, zaman: datetime, metin: str, not_: str = "") -> str:
        satirlar = [f"Proje: {proje.ad} ({len(proje.gorseller)} görsel)",
                    f"Önerilen zaman: {okunur(zaman, self.saat_dilimi)}"]
        if not_:
            satirlar.append(not_)
        elif self.taslak_modu:
            link = self.yayinci.panel_linki() if self.yayinci else "Buffer"
            satirlar += ["", "Senin yapacağın:",
                         f"1. Buffer'ı aç: {link}",
                         "2. Taslaklar bölümünde bu gönderiyi bul, açıklamaya göz at.",
                         "3. Önerilen saate planla. Beğenmezsen düzenle ya da sil."]
        else:
            satirlar.append("Buffer'da planlandı. İstersen Buffer'dan düzenleyip silebilirsin.")
        satirlar += ["", "Açıklama:", "-----", metin, "-----"]
        return "\n".join(satirlar)


def calistir(deneme: bool = False, simdi: datetime | None = None, *, kok: Path = KOK,
             ayar: dict | None = None, yayinci=None, depo=None, aciklama_fn=None,
             bildirici: Bildirici | None = None, en_fazla: int = 0) -> int:
    ayar = ayar or ayarlari_yukle(kok)
    bildirici = bildirici or Bildirici(ayar, deneme=deneme)
    if not ayar.get("aktif", True):
        print("Sistem ayarlardan kapatılmış (aktif: false). Hiçbir şey yapılmadı.")
        return 0
    simdi = simdi or datetime.now(timezone.utc)

    try:
        if yayinci is None and not (deneme and not os.environ.get("BUFFER_API_KEY")):
            yayinci = yayinci_olustur(ayar)
        if depo is None and not deneme:
            depo = Depo(kok)
    except (YayinciHatasi, DepoHatasi) as e:
        bildirici.gonder("Sistem çalışamadı", f"Başlarken sorun çıktı: {e}")
        return 1

    tur = Tur(deneme, simdi, kok, ayar, yayinci, depo, aciklama_fn or aciklama_yaz, bildirici)
    tur.en_fazla = max(0, int(en_fazla or 0))
    try:
        tur.calis()
    except (AciklamaHatasi, YayinciHatasi, DepoHatasi) as e:
        tur.hata_var = True
        bildirici.gonder("Paylaşım hazırlanırken sorun çıktı",
                         f"{e}\n\nHiçbir şey iki kez paylaşılmaz. Bir sonraki çalışmada yeniden denenecek.")
    except Exception as e:  # noqa: BLE001
        tur.hata_var = True
        traceback.print_exc()
        bildirici.gonder("Beklenmeyen hata",
                         f"{type(e).__name__}: {e}\n\nAyrıntı GitHub çalışma günlüğünde.")
    finally:
        try:
            tur.kaydi_yaz("linkedin: kayıt güncellendi [skip ci]")
        except DepoHatasi as e:
            tur.hata_var = True
            bildirici.gonder("Kayıt kaydedilemedi", f"Paylaşım kaydı depoya yazılamadı: {e}")
    print(f"Bitti. Yeni gönderi: {', '.join(tur.yeni_gonderiler) or 'yok'}.")
    return 1 if tur.hata_var else 0


def main() -> int:
    ayirici = argparse.ArgumentParser(description="LinkedIn otomatik paylaşım")
    ayirici.add_argument("--deneme", action="store_true",
                         help="Buffer'a göndermez, kayda ve depoya dokunmaz")
    ayirici.add_argument("--en-fazla", type=int, default=0,
                         help="Bu turda en fazla kaç gönderi hazırlansın (0 = sınırsız)")
    arg = ayirici.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    anahtarlari_yukle()
    return calistir(deneme=arg.deneme, en_fazla=arg.en_fazla)


if __name__ == "__main__":
    sys.exit(main())
