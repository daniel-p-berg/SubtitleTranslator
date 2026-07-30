# SubtitleTranslator

SubtitleTranslator is a privacy-first macOS subtitle utility. It inspects
embedded and sidecar subtitles, searches the official OpenSubtitles REST API,
translates text subtitles with the OpenAI Responses API, performs conservative
timing correction, creates clean SRT files, and remuxes selected subtitle tracks
into MKV without re-encoding media.

## Product Rules

- Never assume a media-library location. Only inspect files or folders selected
  by the user.
- Never move or edit source media during normal operation.
- Final output goes beside the source by default, with a configurable custom
  destination.
- Moving an original to Trash is per-job, disabled by default, and only allowed
  after a replacement MKV passes verification.
- Intermediate subtitle files belong in the configured private workspace.
- Keep API credentials in macOS Keychain. Never write credentials to settings,
  logs, diagnostics, tests, screenshots, or fixtures.
- Do not add telemetry, analytics, crash uploading, update tracking, or a
  developer-operated relay.
- OpenAI requests go directly to OpenAI and contain subtitle text only when the
  user requests translation.
- OpenSubtitles requests use the official API and contain search metadata only
  when the user requests or permits search. Never scrape the website.
- Image subtitle tracks may supply timing evidence but cannot supply translation
  text without an explicit OCR feature.

## Architecture

- `ui.py`: PySide6 interface, workers, onboarding, candidate review, settings.
- `pipeline.py`: language-neutral workflow orchestration.
- `languages.py`: 30 language profiles, identifiers, and editable prompt
  templates.
- `settings.py`: non-secret settings and macOS Keychain migration.
- `extractor.py`: embedded/sidecar discovery, extraction, and SRT cleaning.
- `open_subtitles.py`: official OpenSubtitles REST API integration.
- `translator.py`: OpenAI translation and strict SRT output validation.
- `subtitle_sync.py`: whole-runtime offset, drift, and discontinuity analysis.
- `muxer.py`: transactional MKV remux and post-write verification.
- `media_launcher.py`: direct external mpv launch.
- `dependencies.py`: bundled/PATH/Homebrew media-tool discovery.

## Verification

```bash
python3.12 -m py_compile \
  app_paths.py audio_activity.py chunker.py dependencies.py extractor.py \
  languages.py main.py media_launcher.py muxer.py open_subtitles.py pipeline.py \
  settings.py subtitle_sync.py translator.py ui.py
python3.12 test_pipeline.py
python3.12 -m unittest -v test_product.py
bash -n build.sh
```

Build the current architecture:

```bash
bash build.sh
```

The public beta is ad-hoc signed because the publisher does not currently have
a paid Apple Developer Program membership. Do not claim that it is notarized.
