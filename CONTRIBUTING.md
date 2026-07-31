# Contributing

Contributions are welcome, especially reproducible subtitle-format, timing, and
language-profile fixes.

## Setup

```bash
python3.12 -m pip install -r requirements-dev.txt
python3.12 tools/build_translations.py --check
python3.12 tools/build_translations.py --compile
python3.12 test_pipeline.py
python3.12 -m unittest -v test_product.py
python3.12 main.py
```

FFmpeg and MKVToolNix are needed for end-to-end media tests:

```bash
brew install ffmpeg mkvtoolnix
```

mpv is optional for development:

```bash
brew install mpv
```

## Pull Requests

- Keep media, subtitle dialogue, API keys, credentials, and personal paths out
  of commits and fixtures.
- Use synthetic SRT data for tests.
- Preserve source media and transactional mux behavior.
- Add focused tests for behavior changes.
- Update privacy documentation when adding any network or storage behavior.
- Keep language rules general rather than tailoring matching logic to one title.

Interface corrections are especially welcome. Edit the relevant Qt `.ts` file
under `translations/`, preserve every `{placeholder}` and technical token, then
run the catalog check and compiler above. See
[`translations/README.md`](translations/README.md) for the review checklist.

Run both test suites and `bash -n build.sh` before opening a pull request.
