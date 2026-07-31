
# SubtitleTranslator

## このMacのプライベート設定

macOS Keychain に API 認証を追加して,任意のメディアフォルダーを選択します. メディアツールを確認する アップにはアカウント,テレメトリ,開発者が運営するサーバーはありません.

1. 設定開始
2. Homebrew をインストールする
3. 欠けているツールをインストールする
4. Keychain にAPIキーを保存する
5. メディアファイルを選択
6. 字幕を準備する
7. mpvで開いています

```bash
brew install ffmpeg mkvtoolnix mpv
```

アプリを再起動した後,言語変更が適用されます.

APIの認証は macOS Keychainに留まります サブタイトルの処理とメディアファイルは このMacに留まります OpenAIは,翻訳時にのみ字幕テキストを受け取ります. OpenSubtitlesは検索時にのみ検索メタデータを受信します. 要求は直接これらのプロバイダーに 行きます

[OpenAI](https://platform.openai.com/api-keys) | [OpenSubtitles](https://www.opensubtitles.com/en/consumers) | [mpv](https://mpv.io/installation/)
