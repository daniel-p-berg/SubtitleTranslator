# Interface Translations

SubtitleTranslator ships one Qt Linguist catalog for every supported interface
language other than English, which is the source and fallback language.

The initial catalogs are machine-generated drafts. Product names, executable
commands, paths, placeholders, markup, and keyboard shortcuts are protected by
the generation tooling, but natural-language wording still needs human review.
Review state is tracked in [`STATUS.md`](STATUS.md).

## Correct A Translation

1. Edit the relevant `subtitletranslator_<locale>.ts` file with Qt Linguist or
   a UTF-8 text editor.
2. Keep every `{placeholder}` exactly as written in the source.
3. Keep `SubtitleTranslator`, `OpenAI`, `OpenSubtitles`, Homebrew commands,
   paths, and keyboard shortcuts unchanged.
4. Run:

   ```bash
   python3.12 tools/build_translations.py --check
   python3.12 tools/build_translations.py --compile
   ```

5. Launch the app in that interface language and inspect Prepare, Recent,
   Settings, Media Tools Setup, mpv Setup, and OpenSubtitles candidate review.

For local QA without changing saved preferences:

```bash
SUBTITLE_TRANSLATOR_INTERFACE_LANGUAGE=ar python3.12 main.py
```

`tools/build_translations.py --update` adds newly introduced `tr()` strings to
every catalog without discarding existing translations. New entries remain
unfinished until translated, and catalog validation intentionally fails while
any entry is unfinished.
