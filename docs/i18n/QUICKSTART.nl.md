
# SubtitleTranslator

## Private setup op deze Mac

Voeg uw API-gegevens toe aan macOS Keychain en kies elke media map. Vervolgens bevestig de mediatools. De app heeft geen account, telemetrie of server die door de ontwikkelaar wordt bediend.

1. Start opzetten
2. Installeer Homebrew
3. Installeer ontbrekende tools
4. Bewaar API-sleutels in Keychain
5. Kies een mediabestand
6. Voorbereid ondertiteling
7. Geopend in mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Taalveranderingen gelden na het opnieuw opstarten van de app.

API-gegevens blijven in macOS Keychain . Ondertitelverwerking en mediabestanden blijven op deze Mac. OpenAI ontvangt alleen tekst met ondertiteling wanneer u vertaalt. OpenSubtitles ontvangt alleen zoekmetadata wanneer u zoekt. Verzoeken gaan rechtstreeks naar die aanbieders.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
