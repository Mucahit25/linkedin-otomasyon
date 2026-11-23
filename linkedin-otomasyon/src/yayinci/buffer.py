"""Buffer GraphQL API (https://api.buffer.com) ile LinkedIn gönderisi.

Doğrulanan noktalar (developers.buffer.com, 2026-11-22):
- Kimlik: "Authorization: Bearer <BUFFER_API_KEY>"
- Görsel dosya yüklenemez; herkese açık ve paylaşılana kadar kalıcı URL verilir.
- createPost: text, channelId, schedulingType, mode (addToQueue | customScheduled |
  shareNext | shareNow), dueAt (UTC ISO), saveToDraft, assets [{image:{url}}],
  metadata.linkedin {firstComment, linkAttachment, annotations}: hepsi isteğe bağlı (2026-11-23)
- PostStatus: draft, error, needs_approval, scheduled, sending, sent
Canlı denemeyle doğrulanan (2026-11-22): taslak dueAt'i saklıyor (customScheduled +
saveToDraft) [Instagram kanalında]; birden fazla image asset sırasıyla tek gönderiye gidiyor;
silinen gönderi post(...) sorgusunda boş dönüyor.
"""
from __future__ import annotations

import os
import time as _time
from datetime import datetime, timezone

import requests

from .temel import (GONDERILIYOR, HATA, ONAY_BEKLIYOR, PAYLASILDI, PLANLANDI, TASLAK,
                    Gonderi, Yayinci, YayinciHatasi)

ADRES = "https://api.buffer.com"
PANEL = "https://publish.buffer.com"

_DURUM = {"draft": TASLAK, "scheduled": PLANLANDI, "sending": GONDERILIYOR,
          "sent": PAYLASILDI, "error": HATA, "needs_approval": ONAY_BEKLIYOR}

_GONDERI_ALANLARI = "id text status dueAt"


def _utc_metin(zaman: datetime) -> str:
    return zaman.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _zaman(metin: str | None) -> datetime | None:
    if not metin:
        return None
    return datetime.fromisoformat(metin.replace("Z", "+00:00"))


def _gonderi(dugum: dict) -> Gonderi:
    durum = str(dugum.get("status") or "").lower()
    return Gonderi(id=str(dugum["id"]), durum=_DURUM.get(durum, durum),
                   zaman=_zaman(dugum.get("dueAt")), metin=dugum.get("text") or "")


class BufferYayinci(Yayinci):
    def __init__(self, ayar: dict, anahtar: str | None = None, oturum=None):
        self.anahtar = anahtar or os.environ.get("BUFFER_API_KEY", "")
        if not self.anahtar:
            raise YayinciHatasi("Buffer anahtarı yok (BUFFER_API_KEY).")
        self.kullanici = (ayar.get("hesap", {}).get("linkedin_adi") or "").lower()
        self.oturum = oturum or requests.Session()
        self._org_id: str | None = None
        self._kanal_id: str | None = os.environ.get("BUFFER_LINKEDIN_KANAL_ID") or None

    # --- düşük seviye ---
    def _sorgu(self, sorgu: str, degiskenler: dict | None = None, deneme: int = 3) -> dict:
        for sira in range(deneme):
            try:
                yanit = self.oturum.post(
                    ADRES, json={"query": sorgu, "variables": degiskenler or {}},
                    headers={"Authorization": f"Bearer {self.anahtar}",
                             "Content-Type": "application/json"},
                    timeout=60)
            except requests.RequestException as e:
                if sira == deneme - 1:
                    raise YayinciHatasi(f"Buffer'a bağlanılamadı: {e}", kesin=False) from e
                _time.sleep(5 * (sira + 1))
                continue
            if yanit.status_code == 401:
                raise YayinciHatasi("Buffer anahtarı geçersiz ya da silinmiş.")
            if yanit.status_code == 429:
                bekle = int(yanit.headers.get("Retry-After", "60") or 60)
                if sira == deneme - 1 or bekle > 120:
                    raise YayinciHatasi("Buffer istek sınırı doldu, sonra tekrar denenecek.")
                _time.sleep(bekle)
                continue
            if yanit.status_code >= 500:
                if sira == deneme - 1:
                    raise YayinciHatasi(f"Buffer şu an hata veriyor ({yanit.status_code}).",
                                        kesin=False)
                _time.sleep(5 * (sira + 1))
                continue
            try:
                veri = yanit.json()
            except ValueError as e:
                raise YayinciHatasi(f"Buffer'ın yanıtı okunamadı ({yanit.status_code}).",
                                    kesin=False) from e
            if veri.get("errors"):
                mesaj = "; ".join(str(h.get("message", h)) for h in veri["errors"])
                raise YayinciHatasi(f"Buffer isteği reddetti: {mesaj}")
            return veri.get("data") or {}
        raise YayinciHatasi("Buffer yanıt vermedi.", kesin=False)

    # --- hesap ve kanal ---
    def org_id(self) -> str:
        if not self._org_id:
            veri = self._sorgu("query { account { organizations { id } } }")
            orgler = (veri.get("account") or {}).get("organizations") or []
            if not orgler:
                raise YayinciHatasi("Buffer hesabında organizasyon bulunamadı.")
            self._org_id = orgler[0]["id"]
        return self._org_id

    def kanallar(self) -> list[dict]:
        veri = self._sorgu(
            "query($input: ChannelsInput!) { channels(input: $input) "
            "{ id name displayName service isDisconnected isLocked } }",
            {"input": {"organizationId": self.org_id()}})
        return veri.get("channels") or []

    def kanal_id(self) -> str:
        if self._kanal_id:
            return self._kanal_id
        linkedin = [k for k in self.kanallar() if str(k.get("service")).lower() == "linkedin"]
        if not linkedin:
            raise YayinciHatasi("Buffer'da bağlı LinkedIn hesabı bulunamadı. "
                                "Buffer'a girip LinkedIn profilini bağla.")
        uygun = [k for k in linkedin
                 if self.kullanici and self.kullanici in
                 {str(k.get("name") or "").lower(), str(k.get("displayName") or "").lower()}]
        kanal = (uygun or linkedin)[0]
        if kanal.get("isDisconnected"):
            raise YayinciHatasi("LinkedIn hesabının Buffer bağlantısı kopmuş. "
                                "Buffer'a girip hesabı yeniden bağla.")
        if kanal.get("isLocked"):
            raise YayinciHatasi("LinkedIn kanalı Buffer'da kilitli (plan sınırı olabilir).")
        self._kanal_id = kanal["id"]
        return self._kanal_id

    # --- arayüz ---
    def gonderi_olustur(self, metin: str, gorsel_urlleri: list[str], zaman: datetime,
                        taslak: bool) -> Gonderi:
        girdi = {
            "text": metin,
            "channelId": self.kanal_id(),
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": _utc_metin(zaman),
            "assets": [{"image": {"url": u}} for u in gorsel_urlleri],
        }
        if taslak:
            girdi["saveToDraft"] = True
        try:
            return self._olustur(girdi)
        except YayinciHatasi as e:
            # Taslakta saat kabul edilmiyorsa saatsiz taslak aç (saat bildirimde yazar).
            if taslak and e.kesin and ("dueAt" in str(e) or "mode" in str(e)):
                girdi.pop("dueAt")
                girdi["mode"] = "addToQueue"
                return self._olustur(girdi)
            raise

    def _olustur(self, girdi: dict) -> Gonderi:
        veri = self._sorgu(
            "mutation($input: CreatePostInput!) { createPost(input: $input) { __typename "
            f"... on PostActionSuccess {{ post {{ {_GONDERI_ALANLARI} }} }} "
            "... on MutationError { message } } }",
            {"input": girdi}, deneme=1)  # oluşturma tekrar denenmez: çift gönderi riski
        sonuc = veri.get("createPost") or {}
        if sonuc.get("post"):
            return _gonderi(sonuc["post"])
        raise YayinciHatasi(f"Buffer gönderiyi kabul etmedi: {sonuc.get('message') or sonuc}")

    def _gonderiler(self, durumlar: list[str], adet: int = 50) -> list[Gonderi]:
        veri = self._sorgu(
            "query($input: PostsInput!, $first: Int) { posts(first: $first, input: $input) "
            f"{{ edges {{ node {{ {_GONDERI_ALANLARI} }} }} }} }}",
            {"first": adet, "input": {"organizationId": self.org_id(),
                                      "sort": [{"field": "dueAt", "direction": "desc"}],
                                      "filter": {"status": durumlar,
                                                 "channelIds": [self.kanal_id()]}}})
        kenarlar = ((veri.get("posts") or {}).get("edges")) or []
        return [_gonderi(k["node"]) for k in kenarlar if k.get("node")]

    def planli_gonderileri_getir(self) -> list[Gonderi]:
        return (self._gonderiler(["draft", "scheduled", "needs_approval", "sending"])
                + self._gonderiler(["sent"], adet=20))

    def durum_sorgula(self, gonderi_id: str) -> Gonderi | None:
        try:
            veri = self._sorgu(
                f"query($input: PostInput!) {{ post(input: $input) {{ {_GONDERI_ALANLARI} }} }}",
                {"input": {"id": gonderi_id}})
        except YayinciHatasi as e:
            if e.kesin and "not found" in str(e).lower():
                return None
            raise
        dugum = veri.get("post")
        return _gonderi(dugum) if dugum else None

    def gonderi_sil(self, gonderi_id: str) -> None:
        self._sorgu("mutation($input: DeletePostInput!) { deletePost(input: $input) "
                    "{ __typename } }", {"input": {"id": gonderi_id}})

    def panel_linki(self) -> str:
        return PANEL
