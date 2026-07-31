#!/usr/bin/env python3
"""Generate compact installation guides from the reviewed Qt catalogs."""

from __future__ import annotations

from build_translations import LANGUAGE_CODES, ROOT, read_catalog


OUTPUT_DIR = ROOT / "docs" / "i18n"
RTL_CODES = {"ar", "fa", "he", "ur"}


def _text(catalog: dict[str, str], source: str) -> str:
    return catalog.get(source, source)


def _guide(code: str, catalog: dict[str, str]) -> str:
    rtl_open = '<div dir="rtl">\n\n' if code in RTL_CODES else ""
    rtl_close = "\n</div>\n" if code in RTL_CODES else ""
    steps = (
        "Start Setup",
        "Install Homebrew",
        "Install Missing Tools",
        "Save API Keys to Keychain",
        "Choose a media file",
        "Prepare Subtitles",
        "Open in mpv",
    )
    lines = [
        rtl_open.rstrip(),
        "# SubtitleTranslator",
        "",
        f"## {_text(catalog, 'Private setup on this Mac')}",
        "",
        " ".join(
            (
                _text(
                    catalog,
                    "Add your API credentials to macOS Keychain and choose any "
                    "media folder.",
                ),
                _text(catalog, "Then confirm the media tools."),
                _text(
                    catalog,
                    "The app has no account, telemetry, or developer-operated "
                    "server.",
                ),
            )
        ),
        "",
    ]
    lines.extend(
        f"{index}. {_text(catalog, source)}"
        for index, source in enumerate(steps, start=1)
    )
    lines.extend(
        (
            "",
            "```bash",
            "brew install ffmpeg mkvtoolnix mpv",
            "```",
            "",
            _text(
                catalog,
                "Language changes apply after restarting the app.",
            ),
            "",
            " ".join(
                _text(catalog, source)
                for source in (
                    "API credentials stay in macOS Keychain.",
                    "Subtitle processing and media files stay on this Mac.",
                    "OpenAI receives subtitle text only when you translate.",
                    "OpenSubtitles receives search metadata only when you "
                    "search.",
                    "Requests go directly to those providers.",
                )
            ),
            "",
            "[OpenAI](https://platform.openai.com/api-keys) | "
            "[OpenSubtitles](https://www.opensubtitles.com/en/consumers) | "
            "[mpv](https://mpv.io/installation/)",
            rtl_close.rstrip(),
            "",
        )
    )
    return "\n".join(line for line in lines if line or line == "")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "QUICKSTART.en.md").write_text(
        _guide("en", {}),
        encoding="utf-8",
    )
    for code in LANGUAGE_CODES:
        (OUTPUT_DIR / f"QUICKSTART.{code}.md").write_text(
            _guide(code, read_catalog(code)),
            encoding="utf-8",
        )
    index_lines = [
        "# Localized Quick Starts",
        "",
        "These compact guides are generated from the same draft Qt catalogs "
        "shipped in the app.",
        "",
        "- [en](QUICKSTART.en.md)",
        *(
            f"- [{code}](QUICKSTART.{code}.md)"
            for code in LANGUAGE_CODES
        ),
        "",
    ]
    (OUTPUT_DIR / "README.md").write_text(
        "\n".join(index_lines),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
