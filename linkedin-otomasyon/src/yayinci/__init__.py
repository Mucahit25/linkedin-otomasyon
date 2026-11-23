from .temel import Gonderi, Yayinci, YayinciHatasi  # noqa: F401


def yayinci_olustur(ayar: dict) -> "Yayinci":
    tur = ayar.get("yayinci", {}).get("tur", "buffer")
    if tur == "buffer":
        from .buffer import BufferYayinci
        return BufferYayinci(ayar)
    raise YayinciHatasi(f"Bilinmeyen yayıncı türü: {tur}")
