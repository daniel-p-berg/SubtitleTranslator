
# SubtitleTranslator

## Configuraţie privată pe acest Mac

Adăugați credentiale de API la macOS Keychain și alegeți orice dosar de media. Apoi confirmă instrumentele media. Aplicația nu are niciun cont, telemetrie sau server operat de dezvoltator.

1. Începe setarea
2. Instalarea Homebrew
3. Instalaţi instrumentele lipsă
4. Salvaţi cheile API pentru Keychain
5. Alege un fişier media
6. Pregătiţi subtitrările
7. Deschise în mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Schimbările de limbă se aplică după redeschiderea aplicației.

Credentalele API rămân în macOS Keychain . Procesarea subtitelor și fișierele media rămân pe acest Mac. OpenAI primește textul subtitrat numai atunci când traduceți. OpenSubtitles primeşte metadata de căutare numai atunci când căutaţi. Cererile merg direct la acei furnizori.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
