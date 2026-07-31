
# SubtitleTranslator

## Ustawienie prywatne na tym Mac

Dodaj swoje akredytacje API do macOS Keychain i wybierz dowolny folder multimedialny. Następnie potwierdź narzędzia medialne. Aplikacja nie ma konta, telemetrii ani serwera obsługiwanego przez programistów.

1. Rozpoczęcie konfiguracji
2. Zainstalowanie Homebrew
3. Zainstalowanie brakujących narzędzi
4. Zapisz klucze API do Keychain
5. Wybierz plik prasowy
6. Przygotuj subteksty
7. Otwarte w mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Zmiany języka obowiązują po ponownym uruchomieniu aplikacji.

Poświadczenia API pozostają w macOS Keychain . Przetwarzanie nagłówków i pliki multimedialne pozostają na tym Mac. OpenAI otrzymuje teksty podtytułowe tylko podczas tłumaczenia. OpenSubtitles otrzymuje metadany wyszukiwania tylko podczas wyszukiwania. Wnioski skierowane są bezpośrednio do tych dostawców.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
