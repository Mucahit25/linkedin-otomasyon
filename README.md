# LinkedIn otomatik paylaşım (Concord Design)

> **Render eklemek:** Bilgisayarda `LinkedIn_Paylasim/Renderlari_Buraya_At` klasörüne at.
> Birden fazla görsel tek gönderide olsun istiyorsan bir alt klasöre koy. İstersen klasöre
> `bilgi.txt` ekle (fuar, şehir, m², ahşap/modüler). Firma adını yalnız bilgi notuna yazarsan kullanır.
>
> **Gerisi otomatik:** Bilgisayar her gün (ve her açılışta) yeni renderları GitHub'a gönderir.
> GitHub hemen ve her sabah çalışır: görseli 4:5 yapar, logoyu ekler, LinkedIn metnini yazar,
> hafta içi her güne 1 paylaşım olacak şekilde Buffer'a **taslak** koyar, sana mail atar.
> Sen Buffer'da taslağa bakıp onaylarsın. Hiçbir render iki kez paylaşılmaz.

## Saatler (config.yaml > paylasim)
Pzt 09-10, Sal 08:30-09:30, Çar 12-13, Per 08:30-09:30, Cum 10-11 (İstanbul). Haftada 5.

## Kurallar
- Hedef kitle: stand üreticisi / dekoratör firmalar. Metin "biz" dili, 350-900 karakter, 4 etiket.
- Üretim konusu ne vaat ne inkar edilir. Kullanıcının çalıştığı firmanın adı asla geçmez
  (yasaklı ifadelerde ayrıca kapı var).
- Onay modu açık: Buffer'da taslak. Kapatmak: `onay_modu: false`.

## Teknik not
- Kaynak Instagram_Otomasyon'dan uyarlandı (aynı akış). Depo: GitHub `Mucahit25/linkedin-otomasyon` (public,
  Buffer görselleri raw.githubusercontent adresinden çeker).
- `_yerel/renderlari_gonder.py`: yerel klasör -> depo `linkedin-otomasyon/renderlar/` (API, git yok).
  Windows Görev Zamanlayıcı: "LinkedIn renderlari gonder" (her gün 10:00 + oturum açılışı).
  Kayıt `_yerel/yuklenenler.json`, günlük `_yerel/renderlari_gonder.log`.
- Kod güncelleme: `_yerel/github_yukle.py "mesaj [skip ci]"` (kayit/, hazir/, renderlar/ ASLA gönderilmez).
- Gizli değerler: `_yerel/gizli_yukle.py BUFFER_API_KEY CLAUDE_CODE_OAUTH_TOKEN GMAIL_ADRES GMAIL_UYGULAMA_SIFRESI BILDIRIM_EPOSTA`.
- Elle çalıştırma: `_yerel/calistir_bekle.ps1 [-Deneme] [-EnFazla N]`.
- Testler: `cd linkedin-otomasyon && ..\.venv\Scripts\python.exe -m pytest`.
