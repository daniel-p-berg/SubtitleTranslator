"""Product-level tests for multilingual, privacy, and path behavior."""

from __future__ import annotations

import json
import os
import plistlib
import ssl
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import app_paths
import dependencies
import diagnostics
import extractor
import i18n
import languages
import muxer
import mpv_config
import network_tls
import open_subtitles
from operation_control import (
    CancellationToken,
    OperationCancelled,
    run_process,
)
import settings
import translation_cost
import translator
from tools import build_translations


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


class UsabilitySafetyTests(unittest.TestCase):
    def test_tls_context_uses_bundled_ca_and_requires_verification(self) -> None:
        network_tls.verified_ssl_context.cache_clear()
        self.assertTrue(network_tls.ca_bundle_path().is_file())

        context = network_tls.verified_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_cancellation_terminates_long_running_process(self) -> None:
        token = CancellationToken()
        timer = threading.Timer(0.15, token.cancel)
        started = time.monotonic()
        timer.start()
        try:
            with self.assertRaises(OperationCancelled):
                run_process(
                    ["/bin/sh", "-c", "sleep 10"],
                    cancellation_token=token,
                )
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 2.0)

    def test_mpv_config_preserves_conflicts_and_restores_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mpv.conf"
            original = "hwdec=yes\nsub-pos=44\n"
            path.write_text(original, encoding="utf-8")

            preview = mpv_config.preview_configuration(
                path=path,
                primary_position=91,
                secondary_position=9,
            )
            self.assertEqual(preview.conflicts, ("sub-pos",))
            self.assertIn("hwdec=yes", preview.proposed_text)
            self.assertIn("sub-pos=91", preview.proposed_text)
            self.assertIn(mpv_config.BEGIN_MARKER, preview.proposed_text)

            result = mpv_config.apply_configuration(
                path=path,
                primary_position=91,
                secondary_position=9,
            )
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(result.backup_path.read_text(), original)
            self.assertIn("hwdec=yes", path.read_text())
            self.assertIn("secondary-sub-pos=9", path.read_text())

            mpv_config.restore_backup(result.backup_path, path=path)
            self.assertEqual(path.read_text(), original)

    def test_diagnostics_redact_credentials_and_home_paths(self) -> None:
        recorder = diagnostics.DiagnosticsRecorder(
            app_version="test",
            operation="test",
            media_path="/Users/example/Movies/Example.mkv",
        )
        recorder.record(
            "network",
            "failed",
            api_key="secret-value",
            message=(
                "Authorization sk-exampleSecret123 at "
                "/Users/example/Movies/Example.mkv"
            ),
        )
        report = recorder.report(include_tools=False)
        serialized = json.dumps(report)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("sk-exampleSecret123", serialized)
        self.assertNotIn("/Users/example", serialized)
        self.assertIn("Example.mkv", serialized)

        with tempfile.TemporaryDirectory() as temporary:
            path = diagnostics.write_report(
                Path(temporary) / "diagnostics.json",
                report,
            )
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                stat.S_IRUSR | stat.S_IWUSR,
            )

    def test_translation_presets_and_cost_ranges(self) -> None:
        self.assertEqual(
            translation_cost.QUALITY_PRESETS["economy"],
            ("gpt-5.6-luna", "none"),
        )
        self.assertEqual(
            translation_cost.preset_for("gpt-5.6-terra", "low"),
            "balanced",
        )
        self.assertEqual(
            translation_cost.preset_for("custom-model", "low"),
            "custom",
        )
        estimate = translation_cost.estimate_for_duration(
            120 * 60,
            "gpt-5.6-luna",
            "low",
        )
        self.assertIsNotNone(estimate)
        self.assertGreater(estimate.cost_low, 0)
        self.assertGreater(estimate.cost_high, estimate.cost_low)
        self.assertAlmostEqual(
            translation_cost.cost_from_usage(
                "gpt-5.6-luna",
                100_000,
                50_000,
            ),
            0.40,
        )


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


class InterfaceLocalizationTests(unittest.TestCase):
    def test_interface_registry_matches_all_subtitle_languages(self) -> None:
        interface_codes = {
            item.code for item in i18n.interface_languages()
        }
        subtitle_codes = {item.code for item in languages.all_languages()}
        self.assertEqual(interface_codes, subtitle_codes)
        self.assertEqual(len(interface_codes), 30)

    def test_system_locale_matching_handles_scripts_and_regions(self) -> None:
        self.assertEqual(i18n.match_supported_locale("zh-Hant-HK"), "zh-Hant")
        self.assertEqual(i18n.match_supported_locale("zh_CN"), "zh-Hans")
        self.assertEqual(i18n.match_supported_locale("pt_PT"), "pt-PT")
        self.assertEqual(i18n.match_supported_locale("pt_BR"), "pt-BR")
        self.assertEqual(i18n.match_supported_locale("tl_PH"), "fil")
        self.assertIsNone(i18n.match_supported_locale("sv_SE"))

    def test_macos_preferred_language_beats_neutral_qt_locale(self) -> None:
        preferences = plistlib.dumps(
            {"AppleLanguages": ["vi-VN", "en-US"]}
        )
        completed = SimpleNamespace(
            returncode=0,
            stdout=preferences,
        )
        with (
            mock.patch.object(i18n.sys, "platform", "darwin"),
            mock.patch.object(
                i18n.subprocess,
                "run",
                return_value=completed,
            ),
        ):
            self.assertEqual(
                i18n._macos_preferred_languages(),
                ("vi-VN", "en-US"),
            )

        with mock.patch.object(
            i18n,
            "_macos_preferred_languages",
            return_value=("vi-VN", "en-US"),
        ):
            self.assertEqual(i18n.system_language_code(), "vi")

    def test_rtl_registry_is_explicit_and_limited(self) -> None:
        rtl = {
            item.code
            for item in i18n.interface_languages()
            if item.rtl
        }
        self.assertEqual(rtl, {"ar", "fa", "he", "ur"})

    def test_development_locale_override_is_local_and_explicit(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SUBTITLE_TRANSLATOR_INTERFACE_LANGUAGE": "ar"},
        ):
            self.assertEqual(
                i18n.resolve_language("system").code,
                "ar",
            )

    def test_all_catalogs_are_complete_and_preserve_placeholders(self) -> None:
        self.assertEqual(build_translations.validate_catalogs(), [])

    def test_compiled_catalogs_load_and_contain_real_translations(self) -> None:
        from PySide6.QtCore import QTranslator

        source_count = len(build_translations.source_messages())
        for code in build_translations.LANGUAGE_CODES:
            with self.subTest(language=code):
                path = build_translations.compiled_path(code)
                self.assertTrue(path.is_file())
                translator = QTranslator()
                self.assertTrue(translator.load(str(path)))
                catalog = build_translations.read_catalog(code)
                changed = sum(
                    source != target
                    for source, target in catalog.items()
                )
                self.assertGreater(changed, source_count * 0.75)
                self.assertTrue(
                    translator.translate("QPlatformTheme", "Cancel")
                )

    def test_ts_files_use_stable_app_and_standard_qt_contexts(self) -> None:
        for code in build_translations.LANGUAGE_CODES:
            with self.subTest(language=code):
                root = ET.parse(
                    build_translations.catalog_path(code)
                ).getroot()
                contexts = {
                    context.findtext("name")
                    for context in root.findall("context")
                }
                self.assertEqual(
                    contexts,
                    {
                        i18n.CONTEXT,
                        "QPlatformTheme",
                        "QDialogButtonBox",
                        "QMessageBox",
                    },
                )


class PrivacyAndSettingsTests(unittest.TestCase):
    def test_secret_store_caches_successful_keychain_reads(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "",
                    "OPEN_SUBTITLES_API_KEY": "",
                },
            ),
            mock.patch.object(
                settings.keyring,
                "get_password",
                return_value="cached-secret",
            ) as get_password,
        ):
            store = settings.SecretStore("test.service")
            self.assertEqual(store.get(settings.OPENAI_SECRET), "cached-secret")
            self.assertEqual(store.get(settings.OPENAI_SECRET), "cached-secret")

        get_password.assert_called_once_with(
            "test.service",
            settings.OPENAI_SECRET,
        )

    def test_secret_store_caches_successful_keychain_writes(self) -> None:
        with (
            mock.patch.object(settings.keyring, "set_password") as set_password,
            mock.patch.object(settings.keyring, "get_password") as get_password,
        ):
            store = settings.SecretStore("test.service")
            store.set(settings.OPENAI_SECRET, "new-secret")
            self.assertEqual(store.get(settings.OPENAI_SECRET), "new-secret")

        set_password.assert_called_once_with(
            "test.service",
            settings.OPENAI_SECRET,
            "new-secret",
        )
        get_password.assert_not_called()

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

    def test_legacy_migration_does_not_repeat_completed_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.json"
            path.write_text(
                json.dumps(
                    {
                        settings.OPENAI_SECRET: "first-secret",
                        settings.OPEN_SUBTITLES_SECRET: "second-secret",
                    }
                ),
                encoding="utf-8",
            )

            class FailingSecrets:
                def set(self, name: str, value: str) -> None:
                    if name == settings.OPEN_SUBTITLES_SECRET:
                        raise settings.SecretStorageError("denied")

            with self.assertRaises(settings.SecretStorageError):
                settings.migrate_legacy_credentials(FailingSecrets(), path)

            remaining = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(settings.OPENAI_SECRET, remaining)
            self.assertEqual(
                remaining[settings.OPEN_SUBTITLES_SECRET],
                "second-secret",
            )
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                stat.S_IRUSR | stat.S_IWUSR,
            )

    def test_default_paths_do_not_claim_a_media_library(self) -> None:
        self.assertEqual(app_paths.DEFAULT_MEDIA_DIR, Path.home() / "Downloads")
        self.assertIn(
            Path("Library/Application Support/SubtitleTranslator"),
            settings.WORKSPACE_DIR.relative_to(Path.home()).parents,
        )
        self.assertNotEqual(settings.WORKSPACE_DIR.parent, app_paths.DEFAULT_MEDIA_DIR)
        self.assertEqual(
            settings.DEFAULT_SETTINGS["interface_language"],
            "system",
        )

    def test_invalid_persisted_choices_fall_back_to_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        **settings.DEFAULT_SETTINGS,
                        "version": 1,
                        "target_language": "not-a-language",
                        "source_language": "also-invalid",
                        "interface_language": "invalid-locale",
                        "reasoning_effort": "unlimited",
                        "output_mode": "overwrite",
                        "prompt_overrides": {
                            "vi": "missing required placeholders",
                            "unknown": "also invalid",
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = settings.SettingsStore(path).load()

        self.assertEqual(loaded["version"], settings.DEFAULT_SETTINGS["version"])
        self.assertEqual(
            loaded["target_language"],
            settings.DEFAULT_SETTINGS["target_language"],
        )
        self.assertEqual(
            loaded["source_language"],
            settings.DEFAULT_SETTINGS["source_language"],
        )
        self.assertEqual(
            loaded["interface_language"],
            settings.DEFAULT_SETTINGS["interface_language"],
        )
        self.assertEqual(
            loaded["reasoning_effort"],
            settings.DEFAULT_SETTINGS["reasoning_effort"],
        )
        self.assertEqual(loaded["output_mode"], "alongside")
        self.assertEqual(loaded["prompt_overrides"], {})

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


class DependencySetupTests(unittest.TestCase):
    def test_homebrew_plan_deduplicates_ffmpeg_and_ffprobe(self) -> None:
        self.assertEqual(
            dependencies.homebrew_formulae_for_tools(
                ("ffmpeg", "ffprobe", "mkvmerge", "mpv")
            ),
            ("ffmpeg", "mkvtoolnix", "mpv"),
        )

    def test_homebrew_command_uses_resolved_executable_and_allowlist(self) -> None:
        command = dependencies.homebrew_install_command(
            ("ffmpeg", "mkvtoolnix"),
            executable="/opt/homebrew/bin/brew",
        )
        self.assertEqual(
            command,
            "/opt/homebrew/bin/brew install ffmpeg mkvtoolnix",
        )
        with self.assertRaises(ValueError):
            dependencies.homebrew_install_command(
                ("ffmpeg", "not-a-formula"),
                executable="/opt/homebrew/bin/brew",
            )

    def test_missing_plan_keeps_mpv_optional(self) -> None:
        statuses = (
            dependencies.Dependency("ffmpeg", None, True, ""),
            dependencies.Dependency("ffprobe", None, True, ""),
            dependencies.Dependency("mkvmerge", "/usr/local/bin/mkvmerge", True, ""),
            dependencies.Dependency("mpv", None, False, ""),
        )
        with mock.patch.object(
            dependencies,
            "dependency_status",
            return_value=statuses,
        ):
            self.assertEqual(
                dependencies.missing_homebrew_formulae(),
                ("ffmpeg",),
            )
            self.assertEqual(
                dependencies.missing_homebrew_formulae(include_optional=True),
                ("ffmpeg", "mpv"),
            )

    def test_homebrew_install_opens_only_the_fixed_command_in_terminal(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            mock.patch.object(
                dependencies,
                "resolve_homebrew",
                return_value="/opt/homebrew/bin/brew",
            ),
            mock.patch.object(
                dependencies.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            command = dependencies.launch_homebrew_install(("mpv",))

        self.assertEqual(command, "/opt/homebrew/bin/brew install mpv")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[:2], ["/usr/bin/osascript", "-e"])
        self.assertIn("do script (item 1 of argv)", arguments[2])
        self.assertEqual(arguments[3], "/opt/homebrew/bin/brew install mpv")

    def test_extractor_resolves_newly_installed_tool_at_call_time(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout='{"streams": []}',
            stderr="",
        )
        with (
            mock.patch.object(
                extractor.dependencies,
                "require_tool",
                return_value="/opt/homebrew/bin/ffprobe",
            ),
            mock.patch.object(
                extractor.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            self.assertEqual(extractor.probe_subtitle_streams("/tmp/movie.mkv"), [])

        self.assertEqual(run.call_args.args[0][0], "/opt/homebrew/bin/ffprobe")


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

    def test_recursive_scan_does_not_follow_descendant_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approved = root / "Approved"
            outside = root / "Outside"
            approved.mkdir()
            outside.mkdir()
            outside_video = outside / "Private.mkv"
            outside_video.write_bytes(b"outside")
            (approved / "linked-folder").symlink_to(outside, target_is_directory=True)
            (approved / "linked-file.mkv").symlink_to(outside_video)

            discovered = list(app_paths.iter_files_recursive(approved))
            latest = app_paths.find_latest_video_in_media_dir(approved)

        self.assertEqual(discovered, [])
        self.assertIsNone(latest)

    def test_known_language_sidecar_must_match_in_multi_video_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "Selected.Movie.2026.mkv"
            other = root / "Other.Movie.2025.mkv"
            unrelated = root / "Other.Movie.2025.vi.srt"
            selected.write_bytes(b"selected")
            other.write_bytes(b"other")
            unrelated.write_text(TRANSLATED_SRT, encoding="utf-8")

            matches = extractor.find_external_subtitles(
                str(selected),
                media_roots=[temporary],
                language_code="vi",
            )

        self.assertEqual(matches, [])

    def test_generic_sidecar_is_allowed_in_single_video_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "Movie.mkv"
            subtitles = root / "Subs"
            subtitles.mkdir()
            english = subtitles / "English.srt"
            video.write_bytes(b"video")
            english.write_text(SRT, encoding="utf-8")

            matches = extractor.find_external_subtitles(
                str(video),
                media_roots=[temporary],
                language_code="en",
            )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].path, english.resolve())

    def test_title_language_word_is_not_treated_as_sidecar_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "The.English.Patient.1996.mkv"
            unmarked = root / "The.English.Patient.1996.srt"
            marked = root / "The.English.Patient.1996.en.srt"
            video.write_bytes(b"video")
            unmarked.write_text(SRT, encoding="utf-8")
            marked.write_text(SRT, encoding="utf-8")

            english = extractor.find_external_subtitles(
                str(video),
                media_roots=[temporary],
                language_code="en",
            )
            all_sidecars = extractor.find_external_subtitles(
                str(video),
                media_roots=[temporary],
            )

        self.assertEqual([item.path for item in english], [marked.resolve()])
        by_path = {item.path: item.language for item in all_sidecars}
        self.assertIsNone(by_path[unmarked.resolve()])
        self.assertEqual(by_path[marked.resolve()].code, "en")

    def test_compound_sidecar_language_code_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "Movie.2025.mkv"
            subtitle = root / "Movie.2025.pt_BR.srt"
            video.write_bytes(b"video")
            subtitle.write_text(SRT, encoding="utf-8")

            matches = extractor.find_external_subtitles(
                str(video),
                media_roots=[temporary],
                language_code="pt-BR",
            )

        self.assertEqual([item.path for item in matches], [subtitle.resolve()])


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

    def test_translation_rejects_preamble_and_missing_dialogue(self) -> None:
        with self.assertRaises(translator.TranslationFormatError):
            translator._validate_srt_structure(
                SRT,
                "Here is the translation:\n\n" + TRANSLATED_SRT,
            )
        with self.assertRaises(translator.TranslationFormatError):
            translator._validate_srt_structure(
                SRT,
                TRANSLATED_SRT.replace("Segunda linea", ""),
            )

    def test_translation_rejects_oversized_source_before_api_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "oversized.srt"
            with source.open("wb") as handle:
                handle.truncate(translator._MAX_SOURCE_BYTES + 1)
            with mock.patch.object(translator, "_request_json") as request:
                with self.assertRaisesRegex(ValueError, "too large"):
                    translator.translate_srt(
                        str(source),
                        "memory-only-key",
                        source_language="en",
                        target_language="vi",
                    )
        request.assert_not_called()

    def test_permanent_openai_error_is_not_retried(self) -> None:
        error = translator.OpenAIRequestError(
            "OpenAI request failed (401): invalid key",
            status_code=401,
            retryable=False,
        )
        with (
            mock.patch.object(
                translator,
                "_request_json",
                side_effect=error,
            ) as request,
            mock.patch.object(translator.time, "sleep") as sleep,
        ):
            with self.assertRaises(translator.OpenAIRequestError):
                translator._translate_chunk(
                    "key",
                    SRT,
                    "Translate",
                    "gpt-5.6-luna",
                    "low",
                    1,
                    1,
                )

        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_openai_response_size_is_bounded(self) -> None:
        class FakeResponse(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        oversized = b"x" * (translator._MAX_RESPONSE_BYTES + 1)
        with mock.patch.object(
            translator,
            "urlopen",
            return_value=FakeResponse(oversized),
        ) as urlopen:
            with self.assertRaisesRegex(
                translator.OpenAIRequestError,
                "safety limit",
            ):
                translator._request_json("GET", "/models/test", "key")
        self.assertIs(
            urlopen.call_args.kwargs["context"],
            network_tls.verified_ssl_context(),
        )

    def test_opensubtitles_matches_unicode_titles_and_rejects_wrong_episode(self) -> None:
        matching = open_subtitles.SubtitleCandidate(
            file_id=1,
            release_name="기생충.2019",
            file_name="기생충.2019.srt",
            language="vi",
            download_count=10,
            rating=8.0,
            trusted=True,
            source={
                "attributes": {
                    "feature_details": {
                        "title": "기생충",
                        "year": 2019,
                    }
                }
            },
        )
        self.assertEqual(
            open_subtitles._filter_filename_candidates(
                [matching],
                "/tmp/기생충.2019.mkv",
            ),
            [matching],
        )

        wrong_episode = open_subtitles.SubtitleCandidate(
            file_id=2,
            release_name="나의 드라마 S01E03",
            file_name="나의.드라마.S01E03.srt",
            language="vi",
            download_count=100,
            rating=9.0,
            trusted=True,
            source={
                "attributes": {
                    "feature_details": {
                        "title": "나의 드라마",
                        "season_number": 1,
                        "episode_number": 3,
                    }
                }
            },
        )
        self.assertEqual(
            open_subtitles._filter_filename_candidates(
                [wrong_episode],
                "/tmp/나의.드라마.S01E02.mkv",
            ),
            [],
        )

    def test_opensubtitles_retries_rate_limit_but_not_auth_failure(self) -> None:
        class FakeResponse(BytesIO):
            headers: dict[str, str] = {}

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        rate_limit = urllib.error.HTTPError(
            "https://api.opensubtitles.com/api/v1/infos/languages",
            429,
            "rate limited",
            {"Retry-After": "0"},
            BytesIO(b'{"message":"slow down"}'),
        )
        with (
            mock.patch.object(
                open_subtitles.urllib.request,
                "urlopen",
                side_effect=[
                    rate_limit,
                    FakeResponse(b'{"data":[]}'),
                ],
            ) as urlopen,
            mock.patch.object(open_subtitles.time, "sleep") as sleep,
        ):
            open_subtitles.test_api_key("key")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)

        with (
            mock.patch.object(
                open_subtitles.urllib.request,
                "urlopen",
                side_effect=[
                    TimeoutError("timed out"),
                    FakeResponse(b'{"data":[]}'),
                ],
            ) as urlopen,
            mock.patch.object(open_subtitles.time, "sleep") as sleep,
        ):
            open_subtitles.test_api_key("key")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1.0)

        unauthorized = urllib.error.HTTPError(
            "https://api.opensubtitles.com/api/v1/infos/languages",
            401,
            "unauthorized",
            {},
            BytesIO(b'{"message":"invalid key"}'),
        )
        with (
            mock.patch.object(
                open_subtitles.urllib.request,
                "urlopen",
                side_effect=unauthorized,
            ) as urlopen,
            mock.patch.object(open_subtitles.time, "sleep") as sleep,
        ):
            with self.assertRaises(open_subtitles.OpenSubtitlesError):
                open_subtitles.test_api_key("key")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_opensubtitles_rejects_unsafe_url_and_oversized_archive_entry(self) -> None:
        candidate = open_subtitles.SubtitleCandidate(
            file_id=3,
            release_name="Movie",
            file_name="Movie.srt",
            language="vi",
            download_count=0,
            rating=0,
            trusted=False,
            source={},
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(open_subtitles.OpenSubtitlesError):
                open_subtitles._download_link(
                    "file:///tmp/subtitle.srt",
                    candidate,
                    "/tmp/Movie.mkv",
                    languages.get_language("vi"),
                    Path(temporary),
                )

            archive_data = BytesIO()
            with zipfile.ZipFile(
                archive_data,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.writestr("Movie.srt", b"123456789")
            with (
                mock.patch.object(
                    open_subtitles,
                    "_MAX_ARCHIVE_ENTRY_BYTES",
                    8,
                ),
                self.assertRaises(open_subtitles.OpenSubtitlesError),
            ):
                open_subtitles._write_zip_subtitle(
                    archive_data.getvalue(),
                    "/tmp/Movie.mkv",
                    languages.get_language("vi"),
                    Path(temporary),
                    3,
                )


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

    def test_mux_verification_rejects_unexpected_extra_subtitle_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Movie.mp4"
            output = root / "Movie.mkv"
            subtitle = root / "Movie.vi.srt"
            source.write_bytes(b"s" * (128 * 1024))
            output.write_bytes(b"o" * (128 * 1024))
            subtitle.write_text(TRANSLATED_SRT, encoding="utf-8")
            track = muxer.SubtitleTrack(str(subtitle), "vi", "Vietnamese", True)
            source_probe = {
                "format": {"duration": "100.0"},
                "streams": [],
            }
            output_probe = {
                "format": {"duration": "100.0"},
                "streams": [
                    {"codec_type": "subtitle", "tags": {"language": "vie"}},
                    {"codec_type": "subtitle", "tags": {"language": "eng"}},
                ],
            }
            with (
                mock.patch.object(
                    muxer,
                    "probe_media",
                    side_effect=[source_probe, output_probe],
                ),
                self.assertRaises(RuntimeError),
            ):
                muxer._verify_mux_output(source, output, [track])


if __name__ == "__main__":
    unittest.main()
