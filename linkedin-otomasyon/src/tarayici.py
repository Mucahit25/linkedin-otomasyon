"""renderlar/ klasöründeki paylaşılmamış projeleri bulur.

- Kökteki tek görsel = tekli gönderi.
- Alt klasör = kaydırmalı gönderi; görseller dosya adına göre (doğal sıralama) dizilir.
- proje_id = sha256(sıralı görsel içerik hash'leri) ilk 16 karakter: ad değişse de aynı
  görseller tekrar paylaşılmaz.
- Daha önce paylaşılmış bir görseli içeren proje de paylaşılmaz, kullanıcı uyarılır.
- Sıra "en eski önce": GitHub'da dosya tarihleri anlamsız olduğundan dosyanın depoya ilk
  eklendiği commit tarihi kullanılır; git yoksa dosya tarihi.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

BILGI_DOSYASI = "bilgi.txt"


@dataclass
class Proje:
    proje_id: str
    ad: str                      # renderlar/ içindeki dosya ya da klasör adı
    tur: str                     # tekli | kaydirmali
    gorseller: list[Path]
    hashler: list[str]
    bilgi: str | None = None
    eklenme: float = 0.0


@dataclass
class TaramaSonucu:
    projeler: list[Proje] = field(default_factory=list)
    uyarilar: list[tuple[str, str]] = field(default_factory=list)  # (tekil anahtar, mesaj)


def _dogal_anahtar(yol: Path):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", yol.name)]


def dosya_hash(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def proje_kimligi(hashler: list[str]) -> str:
    return hashlib.sha256("".join(hashler).encode("ascii")).hexdigest()[:16]


def _git_eklenme_tarihleri(klasor: Path) -> dict[Path, float]:
    """Her dosyanın depoya İLK eklendiği commit zamanı. Git yoksa boş döner."""
    git = shutil.which("git")
    if not git:
        return {}
    try:
        kok = subprocess.run([git, "-C", str(klasor), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        cikti = subprocess.run(
            [git, "-C", kok, "-c", "core.quotepath=false", "log", "--diff-filter=A",
             "--format=@%ct", "--name-only", "--", str(klasor)],
            capture_output=True, text=True, encoding="utf-8", check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return {}
    tarihler: dict[Path, float] = {}
    zaman = 0.0
    for satir in cikti.splitlines():
        if satir.startswith("@"):
            zaman = float(satir[1:])
        elif satir.strip():
            # Günlük en yeniden eskiye gelir; üzerine yazarak en eski eklenmeyi tutarız.
            tarihler[(Path(kok) / satir.strip()).resolve()] = zaman
    return tarihler


def _gorsel_mi(yol: Path, uzantilar: set[str]) -> bool:
    return yol.is_file() and not yol.name.startswith(".") and yol.suffix.lower() in uzantilar


def tara(renderlar: Path, ayar: dict, kullanilan_idler: set[str],
         kullanilan_hashler: set[str]) -> TaramaSonucu:
    dosya_ayar = ayar["dosya"]
    uzantilar = {u.lower() for u in dosya_ayar["desteklenen_uzantilar"]}
    uyari_mb = float(dosya_ayar.get("uyari_mb", 25))
    azami_mb = float(dosya_ayar.get("azami_mb", 50))
    carousel_max = int(ayar["paylasim"].get("carousel_max", 10))
    sonuc = TaramaSonucu()
    if not renderlar.is_dir():
        return sonuc

    tarihler = _git_eklenme_tarihleri(renderlar)

    def eklenme(yol: Path) -> float:
        return tarihler.get(yol.resolve(), yol.stat().st_mtime)

    def boyut_suzgeci(dosyalar: list[Path]) -> list[Path]:
        kalan = []
        for d in dosyalar:
            mb = d.stat().st_size / (1024 * 1024)
            if mb > azami_mb:
                sonuc.uyarilar.append((
                    f"buyuk:{d.name}:{d.stat().st_size}",
                    f"'{d.name}' {mb:.0f} MB, sınır {azami_mb:.0f} MB. Bu render atlandı. "
                    f"JPG olarak, daha küçük kaydedip yeniden ekle."))
            else:
                if mb > uyari_mb:
                    sonuc.uyarilar.append((
                        f"iri:{d.name}:{d.stat().st_size}",
                        f"'{d.name}' {mb:.0f} MB. Çalışıyor ama {uyari_mb:.0f} MB altı daha iyi."))
                kalan.append(d)
        return kalan

    adaylar: list[tuple[str, str, list[Path], str | None]] = []
    for oge in sorted(renderlar.iterdir(), key=_dogal_anahtar):
        if oge.name.startswith("."):
            continue
        if _gorsel_mi(oge, uzantilar):
            adaylar.append((oge.name, "tekli", [oge], None))
        elif oge.is_dir():
            gorseller = sorted((p for p in oge.iterdir() if _gorsel_mi(p, uzantilar)),
                               key=_dogal_anahtar)
            if not gorseller:
                continue
            bilgi_yolu = next((p for p in oge.iterdir()
                               if p.is_file() and p.name.lower() == BILGI_DOSYASI), None)
            bilgi = bilgi_yolu.read_text(encoding="utf-8-sig", errors="replace") if bilgi_yolu else None
            adaylar.append((oge.name, "kaydirmali", gorseller, bilgi))

    for ad, tur, gorseller, bilgi in adaylar:
        gorseller = boyut_suzgeci(gorseller)
        if not gorseller:
            continue
        if len(gorseller) > carousel_max:
            sonuc.uyarilar.append((
                f"fazla:{ad}:{len(gorseller)}",
                f"'{ad}' klasöründe {len(gorseller)} görsel var. Bir gönderide en fazla "
                f"{carousel_max} olur, ilk {carousel_max} tanesi kullanılacak."))
            gorseller = gorseller[:carousel_max]
        hashler = [dosya_hash(g) for g in gorseller]
        pid = proje_kimligi(hashler)
        if pid in kullanilan_idler:
            continue
        ortak = [g.name for g, h in zip(gorseller, hashler) if h in kullanilan_hashler]
        if ortak:
            sonuc.uyarilar.append((
                f"tekrar:{pid}",
                f"'{ad}' içinde daha önce paylaşılmış görsel var ({', '.join(ortak)}). "
                f"Aynı render iki kez paylaşılmaz, bu yüzden '{ad}' atlandı. "
                f"Yeni renderları yeni bir klasöre koy."))
            continue
        sonuc.projeler.append(Proje(
            proje_id=pid, ad=ad, tur="kaydirmali" if len(gorseller) > 1 else "tekli",
            gorseller=gorseller, hashler=hashler, bilgi=bilgi,
            eklenme=min(eklenme(g) for g in gorseller)))

    # Aynı görseller hem kökte hem klasörde olabilir: ilk geleni tut.
    gorulen: set[str] = set()
    tekil = []
    for p in sorted(sonuc.projeler, key=lambda p: (p.eklenme, _dogal_anahtar(Path(p.ad)))):
        if gorulen.intersection(p.hashler):
            sonuc.uyarilar.append((
                f"ikiz:{p.proje_id}",
                f"'{p.ad}' içindeki bir görsel başka bir projede de var. Sadece biri paylaşılacak."))
            continue
        gorulen.update(p.hashler)
        tekil.append(p)
    sonuc.projeler = tekil
    return sonuc
