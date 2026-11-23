"""Renderları LinkedIn'e hazırlar: 4:5 bulanık çerçeve + logo, sRGB JPEG.

Render kırpılmaz. Arka plan, aynı renderın büyütülmüş, bulanık ve hafif karartılmış
hali; ön planda renderın tamamı en-boy oranı korunarak ortalanır.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps

LOGO_UZANTILARI = (".png", ".webp", ".jpg", ".jpeg", ".tif", ".tiff")


class GorselHatasi(Exception):
    """Bir görsel açılamadı veya hazırlanamadı."""


def _srgb_yap(img: Image.Image) -> Image.Image:
    """Renk profili varsa sRGB'ye çevirir, sonra RGB moduna indirir."""
    icc = img.info.get("icc_profile")
    if icc:
        try:
            kaynak = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            hedef = ImageCms.createProfile("sRGB")
            mod = "RGBA" if img.mode in ("RGBA", "LA", "PA") else "RGB"
            if img.mode not in ("RGB", "RGBA", "CMYK"):
                img = img.convert(mod)
            img = ImageCms.profileToProfile(img, kaynak, hedef, outputMode=mod)
        except Exception:
            pass  # bozuk profil: profilsiz devam et
    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        img = img.point(lambda v: v / 256).convert("L")
    if img.mode in ("RGBA", "LA", "PA", "P"):
        img = img.convert("RGBA")
        zemin = Image.new("RGB", img.size, (255, 255, 255))
        zemin.paste(img, mask=img.getchannel("A"))
        return zemin
    return img.convert("RGB")


def render_ac(yol: Path) -> Image.Image:
    try:
        with Image.open(yol) as img:
            img = ImageOps.exif_transpose(img)
            img.load()
            return _srgb_yap(img)
    except Exception as e:
        raise GorselHatasi(f"'{yol.name}' açılamadı: {e}") from e


def logo_bul(logo_yolu: Path) -> Path | None:
    """Ayardaki logo yoksa aynı klasördeki ilk görseli logo sayar."""
    if logo_yolu.is_file():
        return logo_yolu
    klasor = logo_yolu.parent
    if not klasor.is_dir():
        return None
    adaylar = sorted(p for p in klasor.iterdir()
                     if p.is_file() and p.suffix.lower() in LOGO_UZANTILARI)
    return adaylar[0] if adaylar else None


def _cerceve(render: Image.Image, g: int, y: int, bulaniklik: float, karartma: float) -> Image.Image:
    # Arka plan: kaplayacak şekilde büyüt, ortadan kırp, bulanıklaştır, karart.
    arka = ImageOps.fit(render, (g, y), method=Image.Resampling.LANCZOS)
    arka = arka.filter(ImageFilter.GaussianBlur(bulaniklik))
    arka = ImageEnhance.Brightness(arka).enhance(max(0.0, 1.0 - karartma))
    # Ön plan: tamamı görünsün.
    on = ImageOps.contain(render, (g, y), method=Image.Resampling.LANCZOS)
    arka.paste(on, ((g - on.width) // 2, (y - on.height) // 2))
    return arka


def _logo_ekle(tuval: Image.Image, logo_yolu: Path, ayar: dict) -> None:
    with Image.open(logo_yolu) as l:
        logo = ImageOps.exif_transpose(l).convert("RGBA")
    g = tuval.width
    hedef_g = max(1, round(g * float(ayar.get("genislik_orani", 0.12))))
    hedef_y = max(1, round(logo.height * hedef_g / logo.width))
    logo = logo.resize((hedef_g, hedef_y), Image.Resampling.LANCZOS)
    opaklik = float(ayar.get("opaklik", 0.85))
    alfa = logo.getchannel("A").point(lambda a: round(a * opaklik))
    logo.putalpha(alfa)
    bosluk = round(g * float(ayar.get("kenar_boslugu_orani", 0.03)))
    konum = ayar.get("konum", "sag_alt")
    x = tuval.width - hedef_g - bosluk if "sag" in konum else bosluk
    y = tuval.height - hedef_y - bosluk if "alt" in konum else bosluk
    tuval.paste(logo, (x, y), logo)


def _kaydet(tuval: Image.Image, hedef: Path, kalite: int, azami_mb: float) -> None:
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    for q in range(kalite, 59, -5):
        tampon = io.BytesIO()
        tuval.save(tampon, "JPEG", quality=q, optimize=True, progressive=True, icc_profile=srgb)
        if tampon.tell() <= azami_mb * 1024 * 1024:
            hedef.write_bytes(tampon.getvalue())
            return
    raise GorselHatasi(f"'{hedef.name}' {azami_mb} MB altına indirilemedi.")


def hazirla(kaynaklar: list[Path], hedef_klasor: Path, gorsel_ayar: dict,
            logo_yolu: Path | None) -> list[Path]:
    """Görselleri hazırlar, hedef klasöre 01.jpg, 02.jpg... olarak yazar."""
    g = int(gorsel_ayar.get("genislik", 1080))
    y = int(gorsel_ayar.get("yukseklik", 1350))
    bulaniklik = float(gorsel_ayar.get("bulaniklik_yaricapi", 40))
    karartma = float(gorsel_ayar.get("arka_plan_karartma", 0.35))
    kalite = int(gorsel_ayar.get("jpeg_kalite", 90))
    azami_mb = float(gorsel_ayar.get("azami_cikti_mb", 8))
    logo_ayar = gorsel_ayar.get("logo", {}) or {}

    hedef_klasor.mkdir(parents=True, exist_ok=True)
    ciktilar = []
    for sira, kaynak in enumerate(kaynaklar, start=1):
        tuval = _cerceve(render_ac(kaynak), g, y, bulaniklik, karartma)
        if logo_yolu:
            try:
                _logo_ekle(tuval, logo_yolu, logo_ayar)
            except Exception as e:
                raise GorselHatasi(f"Logo eklenemedi ({logo_yolu.name}): {e}") from e
        hedef = hedef_klasor / f"{sira:02d}.jpg"
        _kaydet(tuval, hedef, kalite, azami_mb)
        ciktilar.append(hedef)
    return ciktilar


if __name__ == "__main__":  # elle deneme: python src/gorsel.py <render...> <cikti_klasoru>
    import sys
    import yaml

    kok = Path(__file__).resolve().parent.parent
    ayar = yaml.safe_load((kok / "config.yaml").read_text(encoding="utf-8"))
    *girdiler, cikti = sys.argv[1:]
    logo = logo_bul(kok / ayar["gorsel"]["logo"]["dosya"])
    for p in hazirla([Path(x) for x in girdiler], Path(cikti), ayar["gorsel"], logo):
        print(p)
