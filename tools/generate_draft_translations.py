#!/usr/bin/env python3
"""Generate private, offline draft UI catalogs with NLLB-200.

This is a maintainer tool, not an application dependency. Convert the official
NLLB checkpoint with ct2-transformers-converter, then install CTranslate2 and
Transformers in a temporary environment before running it. No API key or user
data is used.
"""

from __future__ import annotations

import argparse
import os
import re

from build_translations import (
    LANGUAGE_CODES,
    read_catalog,
    source_messages,
    write_catalog,
)


MODEL_NAME = "facebook/nllb-200-distilled-600M"
MODEL_REVISION = "f8d333a098d19b4fd9a8b18f94170487ad3f821d"
TARGET_CODES = {
    "vi": "vie_Latn",
    "ko": "kor_Hang",
    "ja": "jpn_Jpan",
    "zh_Hans": "zho_Hans",
    "zh_Hant": "zho_Hant",
    "es": "spa_Latn",
    "pt_BR": "por_Latn",
    "pt_PT": "por_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "pl": "pol_Latn",
    "nl": "nld_Latn",
    "tr": "tur_Latn",
    "ar": "arb_Arab",
    "fa": "pes_Arab",
    "he": "heb_Hebr",
    "hi": "hin_Deva",
    "bn": "ben_Beng",
    "ur": "urd_Arab",
    "id": "ind_Latn",
    "ms": "zsm_Latn",
    "th": "tha_Thai",
    "fil": "tgl_Latn",
    "ro": "ron_Latn",
    "cs": "ces_Latn",
    "el": "ell_Grek",
}

PROTECTED_PATTERN = re.compile(
    r"("
    r"\{[a-z_]+\}"
    r"|</?b>"
    r"|\n+"
    r"|~/[^\s<]+"
    r"|brew install (?:ffmpeg|mkvtoolnix|mpv)"
    r"|MKV, MP4, MOV, M4V, AVI, WebM, TS, or M2TS"
    r"|SubtitleTranslator"
    r"|OpenSubtitles"
    r"|OpenAI"
    r"|Homebrew"
    r"|FFmpeg"
    r"|FFprobe"
    r"|MKVToolNix"
    r"|Keychain"
    r"|macOS"
    r"|Finder"
    r"|Terminal"
    r"|Alt\+v"
    r"|g-S"
    r"|g-s"
    r"|mpv"
    r"|SRT"
    r"|MKV"
    r")"
)


def _marker(index: int) -> str:
    first = chr(ord("A") + (index // 26))
    second = chr(ord("A") + (index % 26))
    return f"ZXQKEEP{first}{second}"


def _protect_source(source: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = _marker(len(replacements))
        replacements[marker] = match.group(0)
        return f" {marker} "

    return PROTECTED_PATTERN.sub(replace, source), replacements


def _restore_source(
    source: str,
    translated: str,
    replacements: dict[str, str],
    fallback: str,
) -> str:
    output = translated
    for marker, original in replacements.items():
        if output.count(marker) != 1:
            print(
                f"Warning: protected marker was lost; preserving prior text: "
                f"{source!r}",
                flush=True,
            )
            return fallback
        output = output.replace(marker, original)
    output = re.sub(r"[ \t]+\n", "\n", output)
    output = re.sub(r"\n[ \t]+", "\n", output)
    output = re.sub(r"[ \t]{2,}", " ", output)
    output = output.replace("<b> ", "<b>").replace(" </b>", "</b>")
    return output.strip()


def _batched(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--languages",
        nargs="*",
        default=list(LANGUAGE_CODES),
        choices=LANGUAGE_CODES,
    )
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument(
        "--ct2-model",
        default=os.environ.get("NLLB_CT2_MODEL", ""),
        help="Path to an int8 CTranslate2 NLLB model.",
    )
    parser.add_argument("--beams", type=int, default=1)
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Translate only unfinished catalog entries.",
    )
    args = parser.parse_args()
    if not args.ct2_model:
        parser.error("--ct2-model or NLLB_CT2_MODEL is required")

    import ctranslate2
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME,
        revision=MODEL_REVISION,
        src_lang="eng_Latn",
    )
    translator = ctranslate2.Translator(
        args.ct2_model,
        device="cpu",
        compute_type="int8",
    )

    sources = source_messages()
    protected_sources = {
        source: _protect_source(source)
        for source in sources
    }
    for code in args.languages:
        existing = read_catalog(code)
        selected_sources = (
            tuple(source for source in sources if source not in existing)
            if args.missing_only
            else sources
        )
        if not selected_sources:
            print(f"Skipping {code}: catalog is complete", flush=True)
            continue
        protected_texts = tuple(
            dict.fromkeys(
                protected_sources[source][0]
                for source in selected_sources
            )
        )
        target_code = TARGET_CODES[code]
        translated_texts: dict[str, str] = {}
        print(
            f"Generating {code}: {len(protected_texts)} messages",
            flush=True,
        )
        for batch in _batched(list(protected_texts), args.batch_size):
            source_tokens = [
                ["eng_Latn", *tokenizer.tokenize(text), "</s>"]
                for text in batch
            ]
            results = translator.translate_batch(
                source_tokens,
                target_prefix=[[target_code] for _text in batch],
                beam_size=args.beams,
                max_decoding_length=192,
            )
            output = [
                tokenizer.convert_tokens_to_string(
                    [
                        token
                        for token in result.hypotheses[0]
                        if token not in {target_code, "</s>"}
                    ]
                )
                for result in results
            ]
            translated_texts.update(zip(batch, output, strict=True))

        translations = dict(existing)
        for source in selected_sources:
            protected, replacements = protected_sources[source]
            translations[source] = _restore_source(
                source,
                translated_texts.get(protected, source),
                replacements,
                existing.get(source, source),
            )
        write_catalog(code, translations)


if __name__ == "__main__":
    main()
