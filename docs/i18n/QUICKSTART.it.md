
# SubtitleTranslator

## Configurazione privata su questo Mac

Aggiungi le tue credenziali API a macOS Keychain e scegli qualsiasi cartella multimediale. Allora conferma gli strumenti dei media. L'app non ha un account, telemetria o server gestito dallo sviluppatore.

1. Iniziare l' impostazione
2. Installare Homebrew
3. Installare gli strumenti mancanti
4. Salvare le chiavi API a Keychain
5. Scegli un file multimediale
6. Preparare i sottotitoli
7. Aperto a mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Le modifiche linguistiche si applicano dopo il riavvio dell'app.

Le credenziali dell' API restano in macOS Keychain . Il trattamento dei sottotitoli e i file multimediali restano su questo Mac. OpenAI riceve il testo sottotitolato solo quando si traduce. OpenSubtitles riceve i metadati della ricerca solo quando la ricerca viene effettuata. Le richieste vanno direttamente a questi fornitori.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
