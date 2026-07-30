"""Language metadata and translation prompt profiles.

The application treats source and target languages symmetrically.  Each
profile maps the identifiers used by OpenSubtitles, ffmpeg/mkvmerge, filenames,
and the translation prompt so the rest of the pipeline can remain language
agnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _title_tokens(value: str) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[^A-Za-z0-9_-]+", value) if part)


@dataclass(frozen=True)
class LanguageProfile:
    """Metadata and translation guidance for one supported language."""

    code: str
    name: str
    opensubtitles_code: str
    mux_code: str
    aliases: tuple[str, ...]
    source_guidance: str
    target_guidance: str
    rtl: bool = False

    @property
    def search_tokens(self) -> frozenset[str]:
        """Return normalized tokens that can identify the language."""
        values = {
            self.code,
            self.code.lower(),
            self.opensubtitles_code,
            self.mux_code,
            self.name,
            *self.aliases,
        }
        return frozenset(_normalize_token(value) for value in values if value)


_BASE_PROMPT_TEMPLATE = """You are a professional subtitle translator.

Translate the supplied SRT dialogue from {source_name} to {target_name}.

Success criteria:
1. Return only valid SRT. Preserve every cue number, timestamp, cue order, and
   blank-line separator exactly. Translate dialogue text only.
2. Do not add explanations, notes, markdown fences, speaker labels, or content
   that is not present in the source.
3. Preserve character names, place names, titles, fictional terminology, and
   branded terms unless an established {target_name} form is clearly standard.
4. Preserve explicitly stated family, social, professional, romantic, and
   hierarchical relationships. Do not invent gender, intimacy, hostility, or
   rank when the source leaves them unstated.
5. Preserve meaning, tone, humor, profanity level, and emotional intensity.
   Prefer natural subtitle dialogue over literal or formal prose.
6. Keep lines concise enough to read on screen. Avoid unnecessary repetition.
7. Preserve meaningful inline emphasis such as <i> and </i>, but do not add
   positioning, font, color, or animation instructions.

Source-language guidance:
{source_guidance}

Target-language guidance:
{target_guidance}
"""


LANGUAGES: tuple[LanguageProfile, ...] = (
    LanguageProfile(
        "en",
        "English",
        "en",
        "eng",
        ("english", "eng"),
        "Resolve contractions and omitted subjects from context without making relationships more explicit than the dialogue does.",
        "Use concise, idiomatic contemporary English. Preserve regional or formal register when it is narratively meaningful.",
    ),
    LanguageProfile(
        "vi",
        "Vietnamese",
        "vi",
        "vie",
        ("vietnamese", "viet", "vn"),
        "Track Vietnamese kinship pronouns and forms of address as relationship evidence; do not flatten them into generic English roles.",
        "Use natural contemporary Vietnamese. Preserve explicit relationships with suitable pronouns; otherwise avoid guessing age, gender, or hierarchy and prefer neutral wording such as toi/ban where natural.",
    ),
    LanguageProfile(
        "ko",
        "Korean",
        "ko",
        "kor",
        ("korean", "kor", "kr"),
        "Preserve the meaning carried by honorifics, speech levels, kinship terms, titles, and omitted subjects without inventing facts.",
        "Use natural Korean speech levels and honorifics that match explicit relationships and tone. Avoid switching register without evidence.",
    ),
    LanguageProfile(
        "ja",
        "Japanese",
        "ja",
        "jpn",
        ("japanese", "jpn", "jp"),
        "Preserve honorifics, titles, relationship terms, register, and context-dependent omitted subjects. Do not over-specify gender.",
        "Use natural Japanese subtitle dialogue with consistent politeness and character voice. Keep established names and fictional terminology stable.",
    ),
    LanguageProfile(
        "zh-Hans",
        "Chinese (Simplified)",
        "zh-cn",
        "chi",
        ("chinese simplified", "simplified chinese", "zh-hans", "zh_cn", "chs", "zho"),
        "Use context to resolve omitted subjects conservatively and preserve titles, kinship terms, idioms, and levels of formality.",
        "Write natural Simplified Chinese with mainland-standard characters and punctuation. Keep names and terminology consistent across cues.",
    ),
    LanguageProfile(
        "zh-Hant",
        "Chinese (Traditional)",
        "zh-tw",
        "chi",
        ("chinese traditional", "traditional chinese", "zh-hant", "zh_tw", "cht", "zht"),
        "Use context to resolve omitted subjects conservatively and preserve titles, kinship terms, idioms, and levels of formality.",
        "Write natural Traditional Chinese with appropriate full-width punctuation. Do not mechanically convert mainland wording when a natural Traditional Chinese expression differs.",
    ),
    LanguageProfile(
        "es",
        "Spanish",
        "es",
        "spa",
        ("spanish", "spa", "espanol"),
        "Preserve explicit distinctions in formality, number, and gender while avoiding assumptions unsupported by context.",
        "Use neutral, internationally understandable Spanish. Preserve usted/tu distinctions when the relationship or source register supports them.",
    ),
    LanguageProfile(
        "pt-BR",
        "Portuguese (Brazil)",
        "pt-br",
        "por",
        ("brazilian portuguese", "portuguese brazil", "pt_br", "pob"),
        "Preserve formality, number, and relationship cues; distinguish source idiom from literal meaning.",
        "Use contemporary Brazilian Portuguese subtitle dialogue, natural contractions, and Brazilian vocabulary. Keep voce/tu usage internally consistent with the chosen register.",
    ),
    LanguageProfile(
        "pt-PT",
        "Portuguese (Portugal)",
        "pt-pt",
        "por",
        ("european portuguese", "portuguese portugal", "pt_pt", "por"),
        "Preserve formality, number, and relationship cues; distinguish source idiom from literal meaning.",
        "Use contemporary European Portuguese spelling, vocabulary, pronouns, and idiom rather than Brazilian localization.",
    ),
    LanguageProfile(
        "fr",
        "French",
        "fr",
        "fre",
        ("french", "fre", "fra"),
        "Preserve explicit formality, number, gender, and relationship cues without manufacturing them.",
        "Use concise, idiomatic contemporary French. Keep tu/vous choices consistent with explicit relationships and changes in social distance.",
    ),
    LanguageProfile(
        "de",
        "German",
        "de",
        "ger",
        ("german", "deu", "ger"),
        "Preserve explicit formality, grammatical number, titles, and relationship cues.",
        "Use natural contemporary German with concise subtitle syntax. Keep du/Sie and title choices consistent with the scene.",
    ),
    LanguageProfile(
        "it",
        "Italian",
        "it",
        "ita",
        ("italian", "ita"),
        "Preserve explicit formality, number, gender, and relationship cues without expanding terse dialogue.",
        "Use natural contemporary Italian. Keep tu/Lei choices and forms of address consistent with explicit social relationships.",
    ),
    LanguageProfile(
        "ru",
        "Russian",
        "ru",
        "rus",
        ("russian", "rus"),
        "Preserve explicit formality, aspect, gender, number, and relationship information while resolving omitted material conservatively.",
        "Use idiomatic contemporary Russian and natural subtitle word order. Keep ty/vy and named forms consistent with the relationship.",
    ),
    LanguageProfile(
        "uk",
        "Ukrainian",
        "uk",
        "ukr",
        ("ukrainian", "ukr"),
        "Preserve explicit formality, gender, number, and relationship information without importing Russian wording.",
        "Use natural contemporary Ukrainian vocabulary and syntax. Keep informal/formal address consistent with explicit relationships.",
    ),
    LanguageProfile(
        "pl",
        "Polish",
        "pl",
        "pol",
        ("polish", "pol"),
        "Preserve explicit gender, formality, titles, and relationship cues while resolving implied subjects conservatively.",
        "Use natural contemporary Polish. Handle pan/pani and informal address consistently with the social relationship.",
    ),
    LanguageProfile(
        "nl",
        "Dutch",
        "nl",
        "dut",
        ("dutch", "nld", "dut"),
        "Preserve explicit formality, number, and relationship cues; treat idioms by meaning rather than surface form.",
        "Use concise contemporary Dutch. Keep jij/u choices consistent and avoid unnecessarily formal written phrasing.",
    ),
    LanguageProfile(
        "tr",
        "Turkish",
        "tr",
        "tur",
        ("turkish", "tur"),
        "Resolve pro-drop subjects only when context supports them and preserve honorific, evidential, and relationship meaning.",
        "Use natural contemporary Turkish and concise subtitle syntax. Preserve formal/informal address and kinship terms consistently.",
    ),
    LanguageProfile(
        "ar",
        "Arabic",
        "ar",
        "ara",
        ("arabic", "ara"),
        "Preserve explicit gender, number, titles, kinship, register, and culturally meaningful forms of address.",
        "Use clear Modern Standard Arabic suitable for broad subtitle audiences while retaining purposeful colloquial flavor when essential to character voice.",
        rtl=True,
    ),
    LanguageProfile(
        "fa",
        "Persian",
        "fa",
        "per",
        ("persian", "farsi", "fas", "per"),
        "Preserve politeness, kinship, titles, omitted subjects, and idiomatic meaning without over-explaining.",
        "Use natural contemporary Persian with correct Persian script and punctuation. Keep formal and informal address consistent.",
        rtl=True,
    ),
    LanguageProfile(
        "he",
        "Hebrew",
        "he",
        "heb",
        ("hebrew", "heb"),
        "Preserve explicit gender, number, register, titles, and relationship cues while avoiding unsupported assumptions.",
        "Use natural contemporary Hebrew with concise subtitle phrasing and consistent grammatical gender based only on available evidence.",
        rtl=True,
    ),
    LanguageProfile(
        "hi",
        "Hindi",
        "hi",
        "hin",
        ("hindi", "hin"),
        "Preserve honorifics, kinship, grammatical gender, register, and relationship cues without flattening culturally meaningful address.",
        "Use natural contemporary Hindi in Devanagari. Keep tu/tum/aap choices and gender agreement consistent with explicit context.",
    ),
    LanguageProfile(
        "bn",
        "Bengali",
        "bn",
        "ben",
        ("bengali", "bangla", "ben"),
        "Preserve honorifics, kinship, social distance, and omitted subjects without inventing relationships.",
        "Use natural contemporary Bengali script and concise subtitle phrasing. Keep forms of address consistent with explicit social distance.",
    ),
    LanguageProfile(
        "ur",
        "Urdu",
        "ur",
        "urd",
        ("urdu", "urd"),
        "Preserve honorifics, kinship, grammatical gender, register, and relationship cues.",
        "Use natural contemporary Urdu in Perso-Arabic script. Keep aap/tum/tu choices and gender agreement consistent with explicit context.",
        rtl=True,
    ),
    LanguageProfile(
        "id",
        "Indonesian",
        "id",
        "ind",
        ("indonesian", "bahasa indonesia", "ind"),
        "Preserve titles, kinship terms, politeness particles, and social relationships without imposing grammatical gender.",
        "Use natural contemporary Indonesian with concise dialogue. Keep aku/saya and kamu/Anda choices consistent with register and relationship.",
    ),
    LanguageProfile(
        "ms",
        "Malay",
        "ms",
        "may",
        ("malay", "bahasa melayu", "msa", "may"),
        "Preserve titles, kinship terms, politeness, and social relationships without imposing grammatical gender.",
        "Use natural contemporary Malay rather than Indonesian localization. Keep pronouns and honorifics consistent with register.",
    ),
    LanguageProfile(
        "th",
        "Thai",
        "th",
        "tha",
        ("thai", "tha"),
        "Preserve particles, titles, kinship terms, politeness, omitted subjects, and relationship cues without over-specifying gender.",
        "Use natural contemporary Thai and appropriate politeness particles only when supported by speaker and context. Keep names consistent.",
    ),
    LanguageProfile(
        "fil",
        "Filipino",
        "tl",
        "tgl",
        ("filipino", "tagalog", "tl", "tgl"),
        "Preserve particles, kinship terms, politeness, code-switching, and social relationships.",
        "Use natural contemporary Filipino/Tagalog. Retain natural English code-switching where Filipino dialogue commonly uses it.",
    ),
    LanguageProfile(
        "ro",
        "Romanian",
        "ro",
        "rum",
        ("romanian", "ron", "rum"),
        "Preserve explicit formality, gender, number, titles, and relationship cues.",
        "Use natural contemporary Romanian and concise subtitle syntax. Keep polite and familiar address consistent.",
    ),
    LanguageProfile(
        "cs",
        "Czech",
        "cs",
        "cze",
        ("czech", "ces", "cze"),
        "Preserve explicit gender, formality, number, titles, and relationship information.",
        "Use natural contemporary Czech. Keep ty/vy choices and grammatical gender consistent with explicit context.",
    ),
    LanguageProfile(
        "el",
        "Greek",
        "el",
        "gre",
        ("greek", "ell", "gre"),
        "Preserve explicit formality, gender, number, titles, and relationship cues.",
        "Use natural contemporary Greek with concise subtitle phrasing. Keep formal and informal address consistent.",
    ),
)


UNKNOWN_LANGUAGE = LanguageProfile(
    "und",
    "Unknown",
    "all",
    "und",
    ("unknown", "undetermined"),
    "Treat the source language conservatively and do not infer relationships that are not explicit.",
    "Use natural subtitle dialogue.",
)


_BY_CODE = {language.code.lower(): language for language in LANGUAGES}
_BY_CODE[UNKNOWN_LANGUAGE.code] = UNKNOWN_LANGUAGE
_BY_TOKEN = {
    token: language
    for language in (*LANGUAGES, UNKNOWN_LANGUAGE)
    for token in language.search_tokens
}


def all_languages() -> tuple[LanguageProfile, ...]:
    """Return the supported languages in UI display order."""
    return LANGUAGES


def get_language(code: str) -> LanguageProfile:
    """Return a language profile by app, API, mux, or alias identifier."""
    normalized = _normalize_token(code)
    language = _BY_CODE.get(code.lower()) or _BY_TOKEN.get(normalized)
    if language is None:
        raise KeyError(f"Unsupported language: {code}")
    return language


def identify_language(value: str, title: str = "") -> LanguageProfile | None:
    """Identify a supported language from metadata and optional track title."""
    for candidate in (value, *_title_tokens(title)):
        language = _BY_TOKEN.get(_normalize_token(candidate))
        if language is not None:
            return language
    return None


def default_prompt_template(target_code: str) -> str:
    """Return the editable prompt template for one target language."""
    target = get_language(target_code)
    return _BASE_PROMPT_TEMPLATE.replace(
        "{target_guidance}",
        target.target_guidance,
    )


def render_translation_prompt(
    source_code: str,
    target_code: str,
    *,
    template_override: str | None = None,
) -> str:
    """Render the default or user-edited prompt for a language pair."""
    source = get_language(source_code)
    target = get_language(target_code)
    template = template_override.strip() if template_override else default_prompt_template(target.code)
    replacements = {
        "{source_name}": source.name,
        "{source_code}": source.code,
        "{source_guidance}": source.source_guidance,
        "{target_name}": target.name,
        "{target_code}": target.code,
        "{target_guidance}": target.target_guidance,
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template.strip()


def validate_prompt_template(template: str) -> tuple[bool, str]:
    """Check that a custom prompt retains the essential dynamic fields."""
    stripped = template.strip()
    if not stripped:
        return False, "Prompt cannot be empty."
    if "{source_name}" not in stripped:
        return False, "Prompt must contain {source_name}."
    if "{target_name}" not in stripped:
        return False, "Prompt must contain {target_name}."
    lowered = stripped.lower()
    if "timestamp" not in lowered or "srt" not in lowered:
        return False, "Prompt must instruct the model to preserve SRT timestamps."
    return True, ""
