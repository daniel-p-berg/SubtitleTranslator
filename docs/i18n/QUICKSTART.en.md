
# SubtitleTranslator

## Private setup on this Mac

Add your API credentials to macOS Keychain and choose any media folder. Then confirm the media tools. The app has no account, telemetry, or developer-operated server.

1. Start Setup
2. Install Homebrew
3. Install Missing Tools
4. Save API Keys to Keychain
5. Choose a media file
6. Prepare Subtitles
7. Open in mpv

```bash
brew install ffmpeg mkvtoolnix mpv
```

Language changes apply after restarting the app.

API credentials stay in macOS Keychain. Subtitle processing and media files stay on this Mac. OpenAI receives subtitle text only when you translate. OpenSubtitles receives search metadata only when you search. Requests go directly to those providers.

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
