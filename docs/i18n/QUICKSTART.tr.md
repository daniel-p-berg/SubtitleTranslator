
# SubtitleTranslator

## Bu Mac'te özel ayarlama

API kimliklerinizi macOS Keychain'a ekleyin ve herhangi bir medya klasörünü seçin. O zaman medya araçlarını doğrulayın. Uygulama hesabı, telemetri veya geliştirici tarafından işletilmiş bir sunucu bulunmuyor.

1. Yapılandırma Başlat
2. Homebrew yükle
3. Kayıp Araçları Kur
4. Keychain için API Anahtarlarını kaydet
5. Bir medya dosyası seçin
6. Altyazılar hazırla
7. mpv ' da açıktır

```bash
brew install ffmpeg mkvtoolnix mpv
```

Uygulama yeniden başlatıldıktan sonra dil değişiklikleri geçerlidir.

API kimlikleri macOS Keychain ' de kalır . Alt başlık işleme ve medya dosyaları bu Mac'te kalır. OpenAI sadece çevirdiğinizde alt başlık metni alır. OpenSubtitles arama metadatalarını yalnızca arama yaptığınızda alır. Talepler doğrudan bu sağlayıcılara gidiyor.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
