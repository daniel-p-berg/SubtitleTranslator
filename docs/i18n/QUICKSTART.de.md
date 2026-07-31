
# SubtitleTranslator

## Privat eingerichtet auf diesem Mac

Fügen Sie Ihre API-Anmeldeinformationen zu macOS Keychain hinzu und wählen Sie einen Medienordner aus. Dann bestätigen Sie die Medienwerkzeuge. Die App verfügt über kein Konto, keine Telemetrie oder einen vom Entwickler betriebenen Server.

1. Start-Einstellung
2. Installieren Sie Homebrew
3. Installieren Sie fehlende Werkzeuge
4. Speichern Sie die API-Schlüssel in Keychain
5. Wählen Sie eine Mediendatei aus
6. Vorbereiten Sie Untertitel
7. Öffnen in mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Sprachenänderungen gelten nach Neustart der App.

Die API-Zertifikate bleiben in macOS Keychain . Untertitelverarbeitung und Mediendateien bleiben auf diesem Mac. OpenAI erhält nur bei Übersetzung Untertiteltext. OpenSubtitles erhält nur Metadaten, wenn Sie suchen. Anfragen gehen direkt an diese Anbieter.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
