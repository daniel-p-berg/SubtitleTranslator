
# SubtitleTranslator

## Pengaturan pribadi pada Mac ini

Tambahkan kredensial API Anda ke macOS Keychain dan pilih folder media mana pun. Kemudian konfirmasi alat media. Aplikasi ini tidak memiliki akun, telemetri, atau server yang dioperasikan oleh pengembang.

1. Mulai Setup
2. Pasang Homebrew
3. Menginstal alat yang hilang
4. Simpan Kunci API ke Keychain
5. Pilih file media
6. Persiapkan Subtitles
7. Buka di mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Perubahan bahasa berlaku setelah restart aplikasi.

Sertifikat API tinggal di macOS Keychain . Pengolahan subtitle dan file media tetap di Mac ini. OpenAI hanya menerima teks subtitle ketika Anda menerjemahkan. OpenSubtitles hanya menerima metadata pencarian ketika Anda mencari. Permintaan pergi langsung ke penyedia.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
