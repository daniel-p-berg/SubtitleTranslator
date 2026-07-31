
# SubtitleTranslator

## Pribadong pag-setup sa Mac na ito

Magdagdag ng iyong mga credentials ng API sa macOS Keychain at pumili ng anumang media folder. Pagkatapos kumpirmahin ang mga tool sa media. Ang app ay walang account, telemetry, o developer-operated server.

1. Simulan ang Pag-setup
2. I-install ang Homebrew
3. I-install ang mga Missing Tool
4. I-save ang mga susi ng API sa Keychain
5. Pumili ng isang media file
6. Maghanda ng mga Subtitle
7. Bukas sa mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Nagpapakita ang mga pagbabago sa wika pagkatapos i-restart ang app.

Ang mga credential ng API ay nakatira sa macOS Keychain . Ang subtitle processing at media files ay mananatili sa Mac na ito. Ang OpenAI ay nakatanggap lamang ng subtitle text kapag isinalin mo ito. Ang OpenSubtitles ay nakatanggap ng metadata ng paghahanap lamang kapag naghahanap ka. Ang mga kahilingan ay direktang pupunta sa mga provider na iyon.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
