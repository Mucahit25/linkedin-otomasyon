"""Git deposu işlemleri: hazır görselleri ve kaydı commit + push eder, görsellerin
herkese açık (raw.githubusercontent.com) adresini verir.

Adres commit SHA'sı ile kurulur: dosya sonradan değişse ya da silinse bile Buffer'ın
çektiği adres değişmez.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import requests


class DepoHatasi(Exception):
    pass


class Depo:
    def __init__(self, klasor: Path):
        self.git = shutil.which("git")
        if not self.git:
            raise DepoHatasi("Git kurulu değil.")
        self.kok = Path(self._calistir("rev-parse", "--show-toplevel", cwd=klasor)).resolve()
        self.slug = os.environ.get("GITHUB_REPOSITORY") or self._uzak_slug()

    def _calistir(self, *argumanlar: str, cwd: Path | None = None) -> str:
        sonuc = subprocess.run([self.git, *argumanlar], cwd=cwd or self.kok,
                               capture_output=True, text=True, encoding="utf-8")
        if sonuc.returncode != 0:
            raise DepoHatasi(f"git {argumanlar[0]} başarısız: "
                             f"{(sonuc.stderr or sonuc.stdout).strip()[-300:]}")
        return sonuc.stdout.strip()

    def _uzak_slug(self) -> str:
        url = self._calistir("remote", "get-url", "origin")
        eslesme = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if not eslesme:
            raise DepoHatasi(f"GitHub deposu adresi anlaşılamadı: {url}")
        return eslesme.group(1)

    def kaydet_gonder(self, yollar: list[Path], mesaj: str) -> str:
        """Verilen yolları commit + push eder, son commit SHA'sını döner."""
        self._calistir("add", "--", *[str(Path(y).resolve()) for y in yollar])
        degisiklik = subprocess.run([self.git, "diff", "--cached", "--quiet"],
                                    cwd=self.kok).returncode != 0
        if degisiklik:
            self._calistir("commit", "-m", mesaj)
        for sira in range(4):
            try:
                self._calistir("push")
                break
            except DepoHatasi:
                if sira == 3:
                    raise
                # Bu arada başka bir değişiklik geldiyse üstüne al ve yeniden dene.
                self._calistir("pull", "--rebase")
                time.sleep(3)
        return self._calistir("rev-parse", "HEAD")

    def ham_url(self, sha: str, yol: Path) -> str:
        goreli = Path(yol).resolve().relative_to(self.kok).as_posix()
        return (f"https://raw.githubusercontent.com/{self.slug}/{sha}/"
                + "/".join(quote(p) for p in goreli.split("/")))


def url_bekle(urller: list[str], sure: int = 180) -> None:
    """Adreslerin herkese açık olarak açıldığını doğrular (Buffer da böyle çekecek)."""
    bitis = time.time() + sure
    kalan = list(urller)
    while kalan:
        kalan = [u for u in kalan if not _acilir_mi(u)]
        if not kalan:
            return
        if time.time() > bitis:
            raise DepoHatasi("Görseller internette açılmadı (depo herkese açık mı?): "
                             + kalan[0])
        time.sleep(10)


def _acilir_mi(url: str) -> bool:
    try:
        return requests.head(url, timeout=30, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False
