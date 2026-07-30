"""Product-level tests for multilingual, privacy, and path behavior."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import app_paths
import extractor
import languages
import muxer
import open_subtitles
import settings
import translator


SRT = """1
00:00:01,000 --> 00:00:02,500
Source line

2
00:00:03,000 --> 00:00:04,500
Second line
"""

TRANSLATED_SRT = """1
00:00:01,000 --> 00:00:02,500
Linea traducida

2
00:00:03,000 --> 00:00:04,500
Segunda linea
"""


class LanguageRegistryTests(unittest.TestCase):
    def test_launch_registry_contains_exactly_thirty_unique_languages(self) -> None:
        profiles = languages.all_languages()
        self.assertEqual(len(profiles), 30)
        self.assertEqual(len({item.code for item in profiles}), 30)
        self.assertEqual(len({item.name for item in profiles}), 30)

    def test_every_language_has_api_and_mux_metadata(self) -> None:
        for profile in languages.all_languages():
            with self.subTest(language=profile.code):
                self.assertTrue(profile.opensubtitles_code)
                self.assertEqual(len(profile.mux_code), 3)
                self.assertTrue(profile.source_guidance)
                self.assertTrue(profile.target_guidance)

    def test_every_prompt_template_validates_and_renders(self) -> None:
        for target in languages.all_languages():
            with self.subTest(language=target.code):
                template = languages.default_prompt_template(target.code)
                valid, message = languages.validate_prompt_template(template)
                self.assertTrue(valid, message)
                rendered = languages.render_translation_prompt("ko", target.code)
                self.assertIn("Korean", rendered)
                self.assertIn(target.name, rendered)
                self.assertNotIn("{source_", rendered)
                self.assertNotIn("{target_", rendered)

    def test_locale_variants_are_identified_separately(self) -> None:
        self.assertEqual(
            languages.identify_language("", "Movie.zh-Hans.srt").code,
            "zh-Hans",
        )
        self.assertEqual(
            languages.identify_language("", "Movie.zh-Hant.srt").code,
            "zh-Hant",
        )
        self.assertEqual(
            languages.identify_language("", "Movie.pt-BR.srt").code,
            "pt-BR",
        )
        self.assertEqual(
            languages.identify_language("", "Movie.pt-PT.srt").code,
            "pt-PT",
        )


class PrivacyAndSettingsTests(unittest.TestCase):
    def test_settings_never_serialize_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            store = settings.SettingsStore(path)
            store.save(
                {
                    **settings.DEFAULT_SETTINGS,
                    "openai_api_key": "secret-openai-value",
                    "opensubtitles_api_key": "secret-search-value",
                }
            )
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-openai-value", text)
            self.assertNotIn("secret-search-value", text)
            self.assertNotIn("api_key", text)
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)

    def test_legacy_plaintext_credentials_are_removed_after_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.json"
            path.write_text(
                json.dumps(
                    {
                        "openai_api_key": "first-secret",
                        "opensubtitles_api_key": "second-secret",
                    }
                ),
                encoding="utf-8",
            )

            class MemorySecrets:
                values: dict[str, str] = {}

                def set(self, name: str, value: str) -> None:
                    self.values[name] = value

            secret_store = MemorySecrets()
            migrated = settings.migrate_legacy_credentials(secret_store, path)
            self.assertTrue(migrated)
            self.assertFalse(path.exists())
            self.assertEqual(
                secret_store.values[settings.OPENAI_SECRET],
                "first-secret",
            )
            self.assertEqual(
                secret_store.values[settings.OPEN_SUBTITLES_SECRET],
                "second-secret",
            )

    def test_default_paths_do_not_claim_a_media_library(self) -> None:
        self.assertEqual(app_paths.DEFAULT_MEDIA_DIR, Path.home() / "Downloads")
        self.assertIn(
            Path("Library/Application Support/SubtitleTranslator"),
            settings.WORKSPACE_DIR.relative_to(Path.home()).parents,
        )
        self.assertNotEqual(settings.WORKSPACE_DIR.parent, app_paths.DEFAULT_MEDIA_DIR)

    def test_public_text_has_no_personal_absolute_paths_or_disallowed_label(self) -> None:
        root = Path(__file__).parent
        suffixes = {".py", ".md", ".sh", ".yml", ".yaml", ".txt", ".spec"}
        disallowed_label = "tor" + "rent"
        personal_path = "/users/" + "daniel" + "berg"
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in {".git", "build", "dist", "release"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            with self.subTest(path=path.name):
                self.assertNotIn(personal_path, text)
                self.assertNotIn(disallowed_label, text)


class MediaDiscoveryTests(unittest.TestCase):
    def test_sidecar_source_can_be_korean_in_nested_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / "Drama"
            media_dir = release / "Video"
            subtitle_dir = release / "Subs"
            media_dir.mkdir(parents=True)
            subtitle_dir.mkdir()
            video = media_dir / "Drama.S01E01.mkv"
            korean = subtitle_dir / "Drama.S01E01.ko.srt"
            video.write_bytes(b"media")
            korean.write_text(SRT, encoding="utf-8")

            candidates = extractor.find_external_subtitles(
                str(video),
                media_roots=[temporary],
            )
            self.assertTrue(candidates)
            self.assertEqual(candidates[0].path.resolve(), korean.resolve())
            self.assertEqual(candidates[0].language.code, "ko")

    def test_generic_stream_selection_uses_requested_source(self) -> None:
        streams = [
            {
                "index": 2,
                "codec_name": "subrip",
                "tags": {"language": "kor", "title": "Korean"},
                "disposition": {"default": 1},
            },
            {
                "index": 3,
                "codec_name": "subrip",
                "tags": {"language": "vie", "title": "Vietnamese"},
                "disposition": {"default": 0},
            },
        ]
        selected = extractor.pick_reference_stream(
            streams,
            preferred_language="ko",
            excluded_language="vi",
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["index"], 2)

    def test_output_names_are_collision_safe_and_source_stays_put(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "Movie.mp4"
            source.write_bytes(b"source")
            first = app_paths.unique_output_path(
                source,
                directory,
                suffix=" [Subtitled]",
                extension=".mkv",
            )
            first.write_bytes(b"output")
            second = app_paths.unique_output_path(
                source,
                directory,
                suffix=" [Subtitled]",
                extension=".mkv",
            )
            self.assertEqual(second.name, "Movie [Subtitled] 2.mkv")
            self.assertTrue(source.exists())


class ApiAndTranslationTests(unittest.TestCase):
    def test_search_uses_selected_target_language(self) -> None:
        calls: list[dict] = []

        def fake_request(
            _method: str,
            _path: str,
            _key: str,
            *,
            query: dict | None = None,
            body: dict | None = None,
        ) -> dict:
            calls.append(query or body or {})
            return {"data": []}

        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "Movie.2025.mkv"
            video.write_bytes(b"x")
            with (
                mock.patch.object(open_subtitles, "movie_hash", return_value=""),
                mock.patch.object(
                    open_subtitles,
                    "_request_json",
                    side_effect=fake_request,
                ),
            ):
                open_subtitles.search_results("key", str(video), "es")
        self.assertTrue(calls)
        self.assertEqual(calls[-1]["languages"], "es")

    def test_translation_composes_source_and_target_prompt(self) -> None:
        captured: dict = {}

        def fake_request(
            _method: str,
            _path: str,
            _key: str,
            *,
            body: dict[str, object] | None = None,
            timeout: int = 240,
        ) -> dict:
            del timeout
            captured.update(body or {})
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": TRANSLATED_SRT,
                            }
                        ],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            with mock.patch.object(
                translator,
                "_request_json",
                side_effect=fake_request,
            ):
                result = translator.translate_srt(
                    str(source),
                    "memory-only-key",
                    source_language="ko",
                    target_language="es",
                )
        self.assertIn("Korean", captured["instructions"])
        self.assertIn("Spanish", captured["instructions"])
        self.assertNotIn("memory-only-key", repr(captured))
        self.assertFalse(captured["store"])
        self.assertIn("Linea traducida", result)

    def test_translation_rejects_changed_timestamps(self) -> None:
        changed = TRANSLATED_SRT.replace("00:00:03,000", "00:00:03,500")
        with self.assertRaises(translator.TranslationFormatError):
            translator._validate_srt_structure(SRT, changed)


class MuxTests(unittest.TestCase):
    def test_mkvmerge_command_uses_language_metadata_and_clean_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Drama.mp4"
            korean = root / "Drama.ko.srt"
            spanish = root / "Drama.es.srt"
            output = root / "Drama [Subtitled].mkv"
            source.write_bytes(b"media")
            korean.write_text(SRT, encoding="utf-8")
            spanish.write_text(TRANSLATED_SRT, encoding="utf-8")
            tracks = [
                muxer.SubtitleTrack(str(spanish), "es", "Spanish", True),
                muxer.SubtitleTrack(str(korean), "ko", "Korean", False),
            ]
            captured: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
                captured.extend(command)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                mock.patch.object(
                    muxer.dependencies,
                    "require_tool",
                    return_value="/usr/local/bin/mkvmerge",
                ),
                mock.patch.object(muxer.subprocess, "run", side_effect=fake_run),
            ):
                muxer._run_mkvmerge(source, tracks, output)

        command_text = " ".join(captured)
        self.assertIn("--no-subtitles", captured)
        self.assertIn("0:spa", captured)
        self.assertIn("0:kor", captured)
        self.assertIn("0:yes", captured)
        self.assertIn("0:no", captured)
        self.assertNotIn("secret", command_text)


if __name__ == "__main__":
    unittest.main()
