from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from PIL import Image

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "src"))

from bildirim import Bildirici  # noqa: E402
from yayinci.temel import PLANLANDI, TASLAK, Gonderi, Yayinci, YayinciHatasi  # noqa: E402

# Pazartesi 23 Kasım 2026, 09:00 İstanbul (06:00 UTC)
PAZARTESI = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)


def gorsel_yaz(yol: Path, renk=(120, 80, 40), boyut=(400, 300)) -> Path:
    yol.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", boyut, renk).save(yol, "JPEG")
    return yol


class SahteYayinci(Yayinci):
    def __init__(self):
        self.gonderiler: dict[str, Gonderi] = {}
        self.olusturma_sayisi = 0
        self.hata_ver: YayinciHatasi | None = None

    def gonderi_olustur(self, metin, gorsel_urlleri, zaman, taslak):
        if self.hata_ver:
            raise self.hata_ver
        self.olusturma_sayisi += 1
        g = Gonderi(id=f"p{self.olusturma_sayisi}", durum=TASLAK if taslak else PLANLANDI,
                    zaman=zaman, metin=metin)
        self.gonderiler[g.id] = g
        return g

    def planli_gonderileri_getir(self):
        return list(self.gonderiler.values())

    def durum_sorgula(self, gonderi_id):
        return self.gonderiler.get(gonderi_id)

    def gonderi_sil(self, gonderi_id):
        self.gonderiler.pop(gonderi_id, None)


class SahteDepo:
    def __init__(self):
        self.commitler: list[str] = []

    def kaydet_gonder(self, yollar, mesaj):
        self.commitler.append(mesaj)
        return f"sha{len(self.commitler)}"

    def ham_url(self, sha, yol):
        return f"https://ornek.test/{sha}/{Path(yol).name}"


def sahte_aciklama(gorseller, bilgi, onceki, gecmis, ayar):
    n = len(onceki) + 1
    return {"aciklama": f"Açıklama {n}", "etiketler": ["#a", "#b", "#c", "#d", "#e"],
            "metin": f"Açıklama {n}\n\n#a #b #c #d #e"}


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    """Geçici bir çalışma klasörü: gerçek config'in kopyası, boş renderlar, logo."""
    ayar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    ayar = copy.deepcopy(ayar)
    ayar["aktif"] = True
    ayar["paylasim"]["onay_modu"] = True
    ayar["bildirim"] = {"eposta": False, "whatsapp": False}
    (tmp_path / "renderlar").mkdir()
    Image.new("RGBA", (200, 100), (255, 255, 255, 200)).save(tmp_path / "logo.png")
    ayar["gorsel"]["logo"]["dosya"] = "logo.png"
    monkeypatch.setattr("depo.url_bekle", lambda urller, sure=180: None)
    monkeypatch.setattr("main.url_bekle", lambda urller, sure=180: None, raising=False)
    return {"kok": tmp_path, "ayar": ayar}


@pytest.fixture
def calistir(ortam):
    import main

    yayinci = SahteYayinci()
    depo = SahteDepo()

    def _calistir(simdi=PAZARTESI, deneme=False):
        bildirici = Bildirici(ortam["ayar"], deneme=deneme)
        kod = main.calistir(deneme=deneme, simdi=simdi, kok=ortam["kok"], ayar=ortam["ayar"],
                            yayinci=yayinci, depo=depo, aciklama_fn=sahte_aciklama,
                            bildirici=bildirici)
        return kod, bildirici

    _calistir.yayinci = yayinci
    _calistir.depo = depo
    return _calistir
