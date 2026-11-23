"""Claude ile Türkçe LinkedIn paylaşım metni ve etiketleri yazar.

İki motor (config: aciklama.motor):
  claude_abonelik: Claude Pro/Max aboneliği, Claude Code komut satırı üzerinden (varsayılan)
  api:             Anthropic API anahtarı (ANTHROPIC_API_KEY), ayrı ücretli

Etiket düzeni (toplam config'teki etiket_sayisi, varsayılan 5):
  sabit etiketler (config) + Claude'un seçtiği 1-2 projeye özel etiket
  + kalan yerler havuzdan dönüşümlü (en uzun süredir kullanılmayan önce).
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import anthropic
from PIL import Image

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SEMA = {
    "type": "object",
    "properties": {
        "aciklama": {"type": "string"},
        "proje_etiketleri": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["aciklama", "proje_etiketleri"],
    "additionalProperties": False,
}

# Bayraklar ve birleşik emojiler dahil kabaca emoji yakalayıcı
_EMOJI = re.compile(
    "[\U0001F1E6-\U0001F1FF]{2}|[\U0001F300-\U0001FAFF☀-➿⬀-⯿]",
)


class AciklamaHatasi(Exception):
    """Açıklama üretilemedi veya kurallara uymadı."""


def tr_kucuk(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def _etiket_normal(e: str) -> str:
    e = e.strip().replace(" ", "")
    if not e.startswith("#"):
        e = "#" + e
    return tr_kucuk(e)


def _kucuk_kopya_b64(yol: Path, kenar: int = 1024) -> str:
    with Image.open(yol) as img:
        img = img.convert("RGB")
        img.thumbnail((kenar, kenar), Image.Resampling.LANCZOS)
        tampon = io.BytesIO()
        img.save(tampon, "JPEG", quality=85)
    return base64.standard_b64encode(tampon.getvalue()).decode("ascii")


def _sistem_metni(ayar: dict, hesap: dict) -> str:
    yasakli = ", ".join(ayar["yasakli_ifadeler"])
    marka = hesap.get("marka_adi") or ""
    marka_kurali = (f"Marka adı: {marka}." if marka
                    else "Açıklamada hiçbir marka veya tasarımcı adı kullanma.")
    return f"""Sen iki kişilik bir fuar standı tasarım ekibinin (Concord Design) LinkedIn paylaşımı için metin yazıyorsun.

Hizmet: {hesap['hizmet']}. Metin tasarımı öne çıkarır.
Üretim, montaj ve kurulum konusuna hiç girme: ne yaptığımızı ne de yapmadığımızı söyle.
"Sadece tasarım yapıyoruz" gibi sınır çizen ya da "anahtar teslim" gibi vaat eden cümle kurma.
{marka_kurali}
Hedef kitle: Türkiye'de ve yurt dışında fuar standı kuran dekoratör / stand firmalarının
sahipleri, proje ve tasarım müdürleri. Onlara yoğun dönemde güvenebilecekleri hızlı, disiplinli
bir 3D tasarım ortağı olduğumuzu, satış yaptıran render kalitesiyle gösteriyoruz.

Dil: Türkçe, "biz" diliyle (ekip iki kişi; "tasarladık", "kurguladık" gibi).
Ton: {ayar['ton']}. Abartısız, kendinden emin. Reklam dili, büyük harfle bağırma, klişe yok.

Metin yapısı (LinkedIn, kısa paragraflar, aralarında boş satır):
1. Akışta durduran, tek satırlık açılış (soru ya da net bir gözlem; "Yeni projemiz" gibi sıradan değil).
2. 2-3 kısa paragraf: tasarım kararı ve gerekçesi (ziyaretçi akışı, marka görünürlüğü,
   ürün sergileme, malzeme seçimi, alan kullanımı). Bilgi notu varsa fuar, şehir, m² kullanılabilir.
   Bir stand firmasının işine yarayacak tek bir profesyonel çıkarım ekle.
3. Son satır tam olarak şu çağrı olsun: "{ayar['cagri']}"

Kurallar:
- Metin en az {ayar.get('min_karakter', 0)}, en fazla {ayar['max_karakter']} karakter (etiketler hariç).
- En fazla {ayar.get('emoji_max', 2)} emoji.
- Açıklamanın içine hashtag (#) yazma; etiketler ayrı alanda.
- Şu ifadeleri hiçbir biçimde kullanma: {yasakli}.
- Bilgi notunda yazmayan firma, fuar, şehir, m², ödül bilgisi uydurma. Not yoksa sadece görselde gördüğünü anlat.
- Renderdaki firma logosunu/adını, bilgi notunda yoksa yazma.
- Rakip veya marka kötüleme yok.
- Önceki gönderilerin açılışlarını ve kalıplarını tekrar etme.

proje_etiketleri: Bu projeye özel 1 veya 2 hashtag. İnsanların gerçekten arattığı etiketler olsun:
stand tipi (öneriler: {', '.join(ayar.get('proje_etiket_onerileri', []))}; sadece görsele veya
bilgi notuna gerçekten uyuyorsa; stand tipini zemin ya da mobilyaya göre değil, taşıyıcı yapıya
(duvarlar, çerçeve, kolonlar) göre seç: ahşap zeminli alüminyum çerçeveli stand #ahşapstand değildir),
bilgi notunda varsa fuar adı veya şehir (örn. #wineurasia, #istanbul),
ya da sektör (örn. #makinefuarı). Renk, duygu ya da uydurma betimleme etiketi (#mavivurgu, #koyutasarım gibi) yazma.
Emin değilsen tek etiket yaz. Boşluksuz, # ile başlayan, küçük harf.
Şunları seçme (zaten ekleniyor): {', '.join(ayar['sabit_etiketler'] + ayar['etiket_havuzu'])}."""


def _kullanici_metni(bilgi: str | None, onceki: list[str], ayar: dict, adet: int) -> str:
    parcalar = []
    if bilgi and bilgi.strip():
        parcalar.append(f"Bilgi notu:\n{bilgi.strip()}")
    else:
        parcalar.append("Bilgi notu yok. Sadece görselden yaz, uydurma bilgi verme.")
    if onceki:
        liste = "\n---\n".join(onceki[-int(ayar.get("onceki_aciklama_sayisi", 10)):])
        parcalar.append(f"Önceki gönderilerin açıklamaları (bunları tekrar etme):\n{liste}")
    else:
        parcalar.append("Bu hesabın ilk otomatik gönderisi.")
    parcalar.append(f"Gönderide {adet} görsel var. Açıklamayı ve proje etiketlerini yaz.")
    return "\n\n".join(parcalar)


def kural_hatalari(aciklama: str, ayar: dict) -> list[str]:
    hatalar = []
    if not aciklama.strip():
        hatalar.append("Açıklama boş.")
    if len(aciklama) > int(ayar["max_karakter"]):
        hatalar.append(f"Açıklama {len(aciklama)} karakter, sınır {ayar['max_karakter']}.")
    if aciklama.strip() and len(aciklama) < int(ayar.get("min_karakter", 0)):
        hatalar.append(f"Açıklama {len(aciklama)} karakter, en az {ayar['min_karakter']} olmalı.")
    kucuk = tr_kucuk(aciklama)
    for yasak in ayar["yasakli_ifadeler"]:
        if tr_kucuk(yasak) in kucuk:
            hatalar.append(f"Yasaklı ifade var: '{yasak}'.")
    # Herkese açık depoda yazmaması gereken ek yasaklar (gizli değer, virgülle ayrılmış).
    gizli = [y.strip() for y in os.environ.get("GIZLI_YASAKLI", "").split(",") if y.strip()]
    for yasak in gizli:
        if tr_kucuk(yasak) in kucuk:
            hatalar.append("Kullanılmaması gereken bir firma adı geçiyor, metinden çıkar.")
    if "#" in aciklama:
        hatalar.append("Açıklamanın içinde hashtag var.")
    emoji = len(_EMOJI.findall(aciklama))
    if emoji > int(ayar.get("emoji_max", 2)):
        hatalar.append(f"{emoji} emoji var, sınır {ayar.get('emoji_max', 2)}.")
    cagri = ayar.get("cagri", "")
    if cagri and _sade(cagri) not in _sade(aciklama):
        hatalar.append(f"Son cümle tam olarak şu çağrı olmalı: \"{cagri}\"")
    return hatalar


def _sade(metin: str) -> str:
    """Karşılaştırma için: küçük harf, tırnak türleri ve fazla boşluk eşitlenir."""
    metin = tr_kucuk(metin).replace("’", "'").replace("‘", "'")
    return " ".join(metin.split())


def etiketleri_kur(proje_etiketleri: list[str], ayar: dict, gecmis_etiketler: list[list[str]]) -> list[str]:
    """Sabit + proje + dönüşümlü havuz etiketlerinden tam etiket_sayisi kadar liste kurar."""
    adet = int(ayar.get("etiket_sayisi", 5))
    secilen: list[str] = []
    for e in [*ayar["sabit_etiketler"], *proje_etiketleri[:2]]:
        n = _etiket_normal(e)
        if len(n) > 1 and n not in secilen and len(secilen) < adet:
            secilen.append(n)
    # Havuz: en son ne zaman kullanıldığına göre sırala (hiç kullanılmamış en başta).
    son_kullanim = {}
    for sira, liste in enumerate(gecmis_etiketler):
        for e in liste:
            son_kullanim[_etiket_normal(e)] = sira
    havuz = [_etiket_normal(e) for e in ayar["etiket_havuzu"]]
    havuz.sort(key=lambda e: son_kullanim.get(e, -1))
    for e in havuz:
        if len(secilen) >= adet:
            break
        if e not in secilen:
            secilen.append(e)
    if len(secilen) != adet:
        raise AciklamaHatasi(f"{adet} etiket kurulamadı (havuz yetersiz).")
    return secilen


def _abonelik_cagir(model: str, sistem: str, gorseller: list[Path], kullanici_metni: str) -> dict:
    """Claude aboneliğiyle (Claude Code komut satırı) çalıştırır.

    Bulutta CLAUDE_CODE_OAUTH_TOKEN ile, yerelde bilgisayardaki Claude girişiyle çalışır.
    ANTHROPIC_API_KEY ortamdan çıkarılır; yoksa abonelik yerine API ücreti kullanılır.
    """
    claude = shutil.which("claude")
    if not claude:
        raise AciklamaHatasi("Claude Code bulunamadı (kurulu değil).")
    with tempfile.TemporaryDirectory(prefix="li_aciklama_") as gecici:
        gecici_yol = Path(gecici)
        yollar = []
        for sira, yol in enumerate(gorseller, start=1):
            hedef = gecici_yol / f"gorsel_{sira:02d}.jpg"
            hedef.write_bytes(base64.standard_b64decode(_kucuk_kopya_b64(yol)))
            yollar.append(str(hedef))
        istem = (
            f"{sistem}\n\n=== GÖREV ===\n"
            f"Önce şu görselleri Read aracıyla tek tek aç ve incele:\n"
            + "\n".join(f"- {y}" for y in yollar)
            + f"\n\n{kullanici_metni}\n\nYanıtını yalnızca istenen JSON yapısında ver."
        )
        ortam = {k: v for k, v in os.environ.items()
                 if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        komut = [claude, "-p", "--output-format", "json",
                 "--json-schema", json.dumps(SEMA),
                 "--model", model, "--tools", "Read", "--allowedTools", "Read",
                 "--max-turns", "10"]
        try:
            sonuc = subprocess.run(komut, input=istem, capture_output=True, text=True,
                                   encoding="utf-8", cwd=gecici, env=ortam, timeout=600)
        except subprocess.TimeoutExpired as e:
            raise AciklamaHatasi("Claude 10 dakikada yanıt vermedi.") from e
    try:
        veri = json.loads(sonuc.stdout)
    except json.JSONDecodeError:
        hata = (sonuc.stderr or sonuc.stdout or "").strip()[-400:]
        if "login" in hata.lower() or "auth" in hata.lower() or "token" in hata.lower():
            raise AciklamaHatasi("Claude aboneliği girişi geçersiz ya da süresi dolmuş.")
        raise AciklamaHatasi(f"Claude çalışmadı: {hata or 'boş yanıt'}")
    if veri.get("is_error") or sonuc.returncode != 0:
        mesaj = str(veri.get("result") or veri.get("subtype") or "bilinmeyen hata")
        if "limit" in mesaj.lower():
            raise AciklamaHatasi("Claude abonelik kullanım sınırı doldu, sonra tekrar denenecek.")
        raise AciklamaHatasi(f"Claude hata verdi: {mesaj[:300]}")
    yapili = veri.get("structured_output")
    if not isinstance(yapili, dict):
        try:
            yapili = json.loads(veri.get("result", ""))
        except (json.JSONDecodeError, TypeError) as e:
            raise AciklamaHatasi("Claude'un yanıtı istenen biçimde değil.") from e
    return yapili


def _claude_cagir(istemci, model: str, sistem: str, mesajlar: list) -> dict:
    yanit = istemci.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SEMA}},
        system=sistem,
        messages=mesajlar,
    )
    if yanit.stop_reason == "refusal":
        raise AciklamaHatasi("Claude bu görseller için açıklama yazmayı reddetti.")
    if yanit.stop_reason == "max_tokens":
        raise AciklamaHatasi("Claude'un yanıtı yarıda kesildi.")
    metin = next((b.text for b in yanit.content if b.type == "text"), "")
    try:
        return json.loads(metin)
    except json.JSONDecodeError as e:
        raise AciklamaHatasi(f"Claude'un yanıtı okunamadı: {e}") from e


def aciklama_yaz(gorseller: list[Path], bilgi: str | None, onceki_aciklamalar: list[str],
                 gecmis_etiketler: list[list[str]], tum_ayar: dict, istemci=None) -> dict:
    """Döner: {'aciklama': str, 'etiketler': [5 etiket], 'metin': gönderi metni}"""
    ayar = tum_ayar["aciklama"]
    sistem = _sistem_metni(ayar, tum_ayar["hesap"])
    secili = gorseller[: int(ayar.get("gorsel_sayisi", 4))]
    metin = _kullanici_metni(bilgi, onceki_aciklamalar, ayar, len(gorseller))
    motor = ayar.get("motor", "claude_abonelik")

    def duzeltme(onceki: dict, hatalar: list[str]) -> str:
        return ("Önceki denemen kurallara uymadı:\n"
                + json.dumps(onceki, ensure_ascii=False)
                + "\nHatalar:\n- " + "\n- ".join(hatalar)
                + "\nKurallara uyan yeni bir açıklama yaz.")

    try:
        if motor == "claude_abonelik":
            sonuc = _abonelik_cagir(ayar["model"], sistem, secili, metin)
            hatalar = kural_hatalari(sonuc.get("aciklama", ""), ayar)
            if hatalar:  # bir kez, hatayı söyleyerek yeniden dene
                sonuc = _abonelik_cagir(ayar["model"], sistem, secili,
                                        metin + "\n\n" + duzeltme(sonuc, hatalar))
                hatalar = kural_hatalari(sonuc.get("aciklama", ""), ayar)
        elif motor == "api":
            istemci = istemci or anthropic.Anthropic()
            icerik = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": _kucuk_kopya_b64(y)}} for y in secili]
            mesajlar = [{"role": "user", "content": [*icerik, {"type": "text", "text": metin}]}]
            sonuc = _claude_cagir(istemci, ayar["model"], sistem, mesajlar)
            hatalar = kural_hatalari(sonuc.get("aciklama", ""), ayar)
            if hatalar:
                mesajlar += [
                    {"role": "assistant", "content": json.dumps(sonuc, ensure_ascii=False)},
                    {"role": "user", "content": duzeltme(sonuc, hatalar)},
                ]
                sonuc = _claude_cagir(istemci, ayar["model"], sistem, mesajlar)
                hatalar = kural_hatalari(sonuc.get("aciklama", ""), ayar)
        else:
            raise AciklamaHatasi(f"Bilinmeyen açıklama motoru: {motor}")
        if hatalar:
            raise AciklamaHatasi("Açıklama iki denemede de kurallara uymadı: " + " ".join(hatalar))
    except anthropic.AuthenticationError as e:
        raise AciklamaHatasi("Anthropic anahtarı geçersiz.") from e
    except anthropic.PermissionDeniedError as e:
        raise AciklamaHatasi("Anthropic hesabı bu işlem için yetkili değil (kredi bitmiş olabilir).") from e
    except anthropic.BadRequestError as e:
        mesaj = str(getattr(e, "message", e))
        if "credit" in mesaj.lower() or "balance" in mesaj.lower():
            raise AciklamaHatasi("Anthropic hesabında kredi bitmiş.") from e
        raise AciklamaHatasi(f"Claude isteği reddetti: {mesaj}") from e
    except anthropic.RateLimitError as e:
        raise AciklamaHatasi("Claude şu an yoğun, istek sınırına takıldı.") from e
    except anthropic.APIStatusError as e:
        raise AciklamaHatasi(f"Claude hatası ({e.status_code}).") from e
    except anthropic.APIConnectionError as e:
        raise AciklamaHatasi("Claude'a bağlanılamadı (internet sorunu).") from e

    aciklama = sonuc["aciklama"].strip()
    etiketler = etiketleri_kur(sonuc.get("proje_etiketleri", []), ayar, gecmis_etiketler)
    return {"aciklama": aciklama, "etiketler": etiketler,
            "metin": f"{aciklama}\n\n{' '.join(etiketler)}"}


if __name__ == "__main__":  # elle deneme: python src/aciklama.py <hazir_gorsel...> [--bilgi dosya]
    import sys

    from ortam import anahtarlari_yukle, ayarlari_yukle

    anahtarlari_yukle()
    argumanlar = sys.argv[1:]
    bilgi = None
    if "--bilgi" in argumanlar:
        i = argumanlar.index("--bilgi")
        bilgi = Path(argumanlar[i + 1]).read_text(encoding="utf-8")
        del argumanlar[i:i + 2]
    s = aciklama_yaz([Path(a) for a in argumanlar], bilgi, [], [], ayarlari_yukle())
    sys.stdout.reconfigure(encoding="utf-8")
    print(s["metin"])
    print(f"\n({len(s['aciklama'])} karakter)")
