# SubtitleTranslator

SubtitleTranslator is a free macOS utility for finding, translating,
synchronizing, cleaning, and merging soft subtitles. It supports dual-subtitle
playback in mpv and works with media stored anywhere the user chooses.

The app has no account, telemetry, analytics, or developer-operated server.
OpenAI and OpenSubtitles requests are sent directly from the Mac using API keys
stored in macOS Keychain.

![SubtitleTranslator Prepare screen](docs/images/prepare.png)

## Features

- Inspects text and image subtitle tracks embedded in common media containers.
- Finds sidecar subtitles in explicitly selected media folders and their nested
  subtitle directories.
- Uses the best available subtitle language as the timing and translation
  source.
- Searches the official OpenSubtitles REST API with hash and title matching.
- Offers manual review when search results are plausible but not safe to select
  automatically.
- Translates text subtitles with configurable OpenAI models and reasoning.
- Includes editable source/target-aware prompt profiles for 30 languages.
- Detects constant offsets, gradual drift, incompatible cuts, and local timing
  discontinuities across the full runtime.
- Tries alternate OpenSubtitles candidates when timing cannot be reconciled.
- Removes style and positioning instructions so mpv controls both subtitle
  locations consistently.
- Creates verified MKV output without re-encoding video or audio.
- Launches current or recent media directly in the user's normal mpv setup.

## Supported Languages

English, Vietnamese, Korean, Japanese, Simplified Chinese, Traditional Chinese,
Spanish, Brazilian Portuguese, European Portuguese, French, German, Italian,
Russian, Ukrainian, Polish, Dutch, Turkish, Arabic, Persian, Hebrew, Hindi,
Bengali, Urdu, Indonesian, Malay, Thai, Filipino, Romanian, Czech, and Greek.

All 30 languages can be used as source or target languages. Unidentified text
subtitles can still provide timing evidence, but their source language must be
selected before translation.

## Install

1. Download the DMG matching the Mac from
   [GitHub Releases](https://github.com/daniel-p-berg/SubtitleTranslator/releases).
2. Drag `SubtitleTranslator.app` into Applications.
3. Because this beta is not notarized, right-click the app, choose **Open**, and
   confirm the first launch.
4. Install the local media tools:

   ```bash
   brew install ffmpeg mkvtoolnix mpv
   ```

The single universal build runs natively on both Apple Silicon and Intel Macs.
macOS 13 or newer is required.

## API Setup

### OpenAI

1. Create an API key at the
   [OpenAI API key page](https://platform.openai.com/api-keys).
2. Confirm API billing and model access in the OpenAI account.
3. Open **Settings > API Connections**, enter the key, and choose
   **Save Keys to Keychain**.
4. Use **Test** to validate the selected model without submitting subtitle text.

The economical default is `gpt-5.6-luna` with low reasoning. Terra, Sol, other
reasoning levels, and custom model identifiers are available in Settings.

### OpenSubtitles

1. Sign in or create an account at
   [OpenSubtitles](https://www.opensubtitles.com/).
2. Create an API consumer key from the
   [API consumers page](https://www.opensubtitles.com/en/consumers).
3. Add it under **Settings > API Connections** and save it to Keychain.

Subtitle availability, rate limits, and download quotas are controlled by
OpenSubtitles.

## File Behavior

- Choose any individual media file from the Prepare screen.
- Add one or more media folders to make recent-file access and nested sidecar
  discovery convenient.
- The app never scans outside selected files and registered folders.
- The original media stays in place and remains unmodified.
- Working subtitles default to:

  ```text
  ~/Library/Application Support/SubtitleTranslator/Workspace/
  ```

- Final SRT and MKV files are written beside the source by default.
- A global custom output folder can be selected in Settings.
- Existing files are never overwritten; numbered filenames are created.
- Working subtitles can be cleaned after a successful job.
- Moving the original to Trash is an explicit per-job option available only
  when creating a replacement MKV.

## mpv Dual Subtitles

Install mpv through Homebrew:

```bash
brew install mpv
```

Create or edit `~/.config/mpv/mpv.conf`:

```conf
sub-pos=88
secondary-sub-pos=12
```

Useful default controls:

| Control | Action |
| --- | --- |
| `g-s` | Select the primary subtitle |
| `g-S` | Select the secondary subtitle |
| `Alt+v` | Toggle the secondary subtitle |

SubtitleTranslator outputs clean SRT tracks without embedded positioning, so
mpv remains responsible for primary and secondary placement. See the
[mpv manual](https://mpv.io/manual/stable/) for additional styling, language,
and delay options.

## Translation Prompts

The prompt system combines:

- Structural SRT requirements shared by every translation.
- Guidance for the detected or selected source language.
- Guidance for the selected target language.

Each target template is visible under **Settings > Translation**. Templates can
be edited, saved per language, or reset. `{source_name}` and `{target_name}`
must remain in custom templates, and timestamp-preservation instructions are
validated before saving.

## Timing Strategy

The pipeline prefers timing evidence in this order:

1. Embedded text subtitle from the selected media.
2. Validated sidecar text subtitle.
3. Embedded or sidecar image-subtitle packet timing.
4. Coarse local audio activity as a last-resort guardrail.

Translated subtitles inherit the source cue timings. Existing target-language
subtitles are checked across the runtime for offset, drift, and discontinuities.
Low-confidence candidates are rejected when alternatives can be tested.

Image subtitle formats such as PGS and VobSub contain pictures rather than
translation text. They can help with timing, but this beta does not perform OCR
or audio transcription.

## Privacy

Read [PRIVACY.md](PRIVACY.md) for the exact local and network data boundary.
In short:

- API keys are stored in macOS Keychain.
- Media files are processed locally.
- Subtitle text goes to OpenAI only for a requested translation.
- Search metadata goes to OpenSubtitles only for a requested or automatic
  search.
- No data is sent to the developer.

## Development

```bash
git clone https://github.com/daniel-p-berg/SubtitleTranslator.git
cd SubtitleTranslator
python3.12 -m pip install -r requirements-dev.txt
python3.12 test_pipeline.py
python3.12 -m unittest -v test_product.py
python3.12 main.py
```

Build a local unsigned release:

```bash
bash build.sh
```

Release automation builds and verifies one universal2 artifact on GitHub
Actions. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md),
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before submitting changes.

## License

SubtitleTranslator is released under the [MIT License](LICENSE). FFmpeg,
MKVToolNix, mpv, Qt/PySide, and API services have their own licenses and terms.
See [Third-Party Notices](THIRD_PARTY_NOTICES.md) for bundled components.
