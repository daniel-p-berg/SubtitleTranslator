#!/usr/bin/env python3
"""Extract, validate, and compile SubtitleTranslator Qt catalogs."""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_DIR = ROOT / "translations"
CONTEXT = "SubtitleTranslator"
PLACEHOLDER_PATTERN = re.compile(r"\{[a-z_]+\}")
PROTECTED_PATTERN = re.compile(
    r"</?b>"
    r"|brew install (?:ffmpeg|mkvtoolnix|mpv)"
    r"|~/[^\s<]+"
    r"|SubtitleTranslator"
    r"|OpenSubtitles"
    r"|OpenAI"
    r"|Homebrew"
    r"|Alt\+v"
    r"|(?<!\w)g-[Ss](?!\w)"
    r"|mpv"
    r"|SRT"
    r"|MKV",
    re.IGNORECASE,
)
LANGUAGE_CODES = (
    "vi",
    "ko",
    "ja",
    "zh_Hans",
    "zh_Hant",
    "es",
    "pt_BR",
    "pt_PT",
    "fr",
    "de",
    "it",
    "ru",
    "uk",
    "pl",
    "nl",
    "tr",
    "ar",
    "fa",
    "he",
    "hi",
    "bn",
    "ur",
    "id",
    "ms",
    "th",
    "fil",
    "ro",
    "cs",
    "el",
)
QT_STANDARD_MESSAGES = (
    "OK",
    "Cancel",
    "Close",
    "Open",
    "&Yes",
    "&No",
    "Save",
    "Discard",
    "Apply",
    "Reset",
    "Help",
    "Restore Defaults",
)


def source_messages() -> tuple[str, ...]:
    """Extract literal tr() arguments in source order."""
    discovered: list[tuple[int, int, str]] = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
            ):
                continue
            argument = node.args[0]
            if not (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
            ):
                raise ValueError(
                    f"{path.name}:{node.lineno} uses a non-literal tr() message"
                )
            discovered.append(
                (
                    list(sorted(ROOT.glob("*.py"))).index(path),
                    node.lineno,
                    argument.value,
                )
            )
    discovered.sort()
    messages = tuple(dict.fromkeys(item[2] for item in discovered))
    return tuple(dict.fromkeys((*messages, *QT_STANDARD_MESSAGES)))


def catalog_path(code: str) -> Path:
    return TRANSLATIONS_DIR / f"subtitletranslator_{code}.ts"


def compiled_path(code: str) -> Path:
    return TRANSLATIONS_DIR / f"subtitletranslator_{code}.qm"


def read_catalog(code: str) -> dict[str, str]:
    """Read completed translations from one Qt Linguist source file."""
    path = catalog_path(code)
    if not path.is_file():
        return {}
    # Catalogs are repository-owned Qt sources, not user-provided XML.
    root = ET.parse(path).getroot()  # nosec B314
    translations: dict[str, str] = {}
    for message in root.findall(f"./context[name='{CONTEXT}']/message"):
        source = message.findtext("source", default="")
        translation = message.find("translation")
        if (
            source
            and translation is not None
            and translation.get("type") != "unfinished"
            and translation.text
        ):
            translations[source] = translation.text
    return translations


def write_catalog(code: str, translations: dict[str, str]) -> None:
    """Write a deterministic Qt Linguist catalog."""
    root = ET.Element(
        "TS",
        {
            "version": "2.1",
            "language": code,
            "sourcelanguage": "en",
        },
    )
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = CONTEXT
    for source in source_messages():
        message = ET.SubElement(context, "message")
        ET.SubElement(message, "source").text = source
        translated = _normalize_translation(
            source,
            translations.get(source, ""),
        )
        translation = ET.SubElement(message, "translation")
        if translated:
            translation.text = translated
        else:
            translation.set("type", "unfinished")
    for context_name in ("QPlatformTheme", "QDialogButtonBox", "QMessageBox"):
        qt_context = ET.SubElement(root, "context")
        ET.SubElement(qt_context, "name").text = context_name
        for source in QT_STANDARD_MESSAGES:
            message = ET.SubElement(qt_context, "message")
            ET.SubElement(message, "source").text = source
            translation = ET.SubElement(message, "translation")
            translated = _normalize_translation(
                source,
                translations.get(source, ""),
            )
            if translated:
                translation.text = translated
            else:
                translation.set("type", "unfinished")
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    tree.write(
        catalog_path(code),
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=False,
    )


def _normalize_translation(source: str, target: str) -> str:
    """Remove common generation artifacts without changing valid punctuation."""
    target = target.strip()
    if source.startswith("&") and target and not target.startswith("&"):
        target = f"&{target}"
    if not source.lstrip().startswith(("-", "•")):
        while target.startswith(("- ", "• ")):
            target = target[2:].lstrip()
    return target


def update_catalogs() -> None:
    """Merge newly extracted sources without discarding translated text."""
    for code in LANGUAGE_CODES:
        write_catalog(code, read_catalog(code))


def validate_catalogs() -> list[str]:
    """Return catalog coverage and placeholder errors."""
    errors: list[str] = []
    expected = set(source_messages())
    for code in LANGUAGE_CODES:
        path = catalog_path(code)
        if not path.is_file():
            errors.append(f"{code}: catalog is missing")
            continue
        translated = read_catalog(code)
        missing = expected - set(translated)
        extra = set(translated) - expected
        if missing:
            errors.append(f"{code}: {len(missing)} untranslated message(s)")
        if extra:
            errors.append(f"{code}: {len(extra)} obsolete message(s)")
        for source, target in translated.items():
            if "ZXQKEEP" in target:
                errors.append(
                    f"{code}: unreplaced generation marker for {source!r}"
                )
            source_placeholders = set(PLACEHOLDER_PATTERN.findall(source))
            target_placeholders = set(PLACEHOLDER_PATTERN.findall(target))
            if source_placeholders != target_placeholders:
                errors.append(
                    f"{code}: placeholder mismatch for {source!r}: "
                    f"{sorted(target_placeholders)}"
                )
            source_tokens = Counter(
                token.casefold()
                for token in PROTECTED_PATTERN.findall(source)
            )
            target_tokens = Counter(
                token.casefold()
                for token in PROTECTED_PATTERN.findall(target)
            )
            if source_tokens != target_tokens:
                errors.append(
                    f"{code}: protected token mismatch for {source!r}"
                )
    return errors


def compile_catalogs() -> None:
    """Compile validated .ts files into Qt runtime .qm resources."""
    errors = validate_catalogs()
    if errors:
        raise RuntimeError("\n".join(errors))
    lrelease = next(
        (
            str(candidate)
            for candidate in (
                Path(sys.executable).with_name("pyside6-lrelease"),
                Path(shutil.which("pyside6-lrelease") or ""),
                Path(shutil.which("lrelease") or ""),
            )
            if candidate.is_file()
        ),
        "",
    )
    if not lrelease:
        raise FileNotFoundError("pyside6-lrelease is required.")
    for code in LANGUAGE_CODES:
        subprocess.run(
            [
                lrelease,
                str(catalog_path(code)),
                "-qm",
                str(compiled_path(code)),
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()
    if not any((args.update, args.check, args.compile)):
        parser.error("choose --update, --check, or --compile")

    if args.update:
        update_catalogs()
    if args.check:
        errors = validate_catalogs()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            raise SystemExit(1)
        print(
            f"{len(LANGUAGE_CODES)} catalogs cover "
            f"{len(source_messages())} messages."
        )
    if args.compile:
        compile_catalogs()


if __name__ == "__main__":
    main()
