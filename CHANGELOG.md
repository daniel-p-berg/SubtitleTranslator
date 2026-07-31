# Changelog

## 0.9.0-beta.11

- Clarified the automatic-review choices as **Use Selected Subtitle** and
  **Translate Source Instead**.
- Added direct copy explaining that the OpenAI action skips the displayed
  OpenSubtitles results before showing the estimated translation cost.

## 0.9.0-beta.10

- Stopped Automatic mode from falling through to a paid OpenAI translation
  without an explicit user action.
- Added a review pause when no OpenSubtitles candidate can be selected safely,
  including timing-rejection details, the full result list, and a one-click
  Translate action with an estimated cost reminder.
- Separated explicitly approved recursive media folders from exact recent-file
  history, preventing a chosen file's parent folder from becoming a scan root.
- Migrated legacy mixed folder history conservatively and kept recent selected
  and generated media available without scanning their surrounding folders.

## 0.9.0-beta.9

- Preserved one full, primary embedded PGS source subtitle when no clean text
  source is available, without OCR or image re-encoding.
- Made the app's mpv launcher inspect subtitle formats and explicitly place PGS
  as the primary track and translated text as the top secondary track.
- Prevented the launcher from automatically pairing two bitmap subtitle tracks,
  which would render in their authored positions and could overlap.
- Reduced the OpenSubtitles connection test to one request with an eight-second
  timeout while retaining normal retries for searches and downloads.

## 0.9.0-beta.8

- Removed all Keychain secret reads and writes from application startup.
- Replaced delete-and-recreate credential updates with an in-place macOS
  Keychain update, so **Allow** grants the current request as expected.
- Changed setup connection tests to access only the provider being tested.
- Added metadata-only credential status checks and safe cleanup of confirmed
  legacy plaintext duplicates.
- Limited each workflow to the API credentials it can actually use.

## 0.9.0-beta.7

- Prevented repeated macOS Keychain prompts by caching each successful
  credential read or write for the lifetime of the app.
- Made legacy credential migration remove each plaintext key immediately after
  that key reaches Keychain, so a later denial does not repeat completed work.

## 0.9.0-beta.6

- Fixed certificate verification failures in the universal build for OpenAI,
  OpenSubtitles, and subtitle-download HTTPS connections.
- Added a bundled Mozilla CA trust store while keeping hostname and certificate
  verification mandatory.
- Added packaged trust-store and verified-context regression coverage.

## 0.9.0-beta.5

- Fixed first-run language detection when Qt reports a neutral locale instead
  of the Mac's preferred interface language.
- Added an interface-language chooser before the readiness checklist so
  onboarding is constructed in the selected language.
- Added the conventional Applications shortcut to the DMG installation window.
- Updated the macOS bundle build number for the replacement beta.

## 0.9.0-beta.4

- Added cooperative cancellation for OpenSubtitles search and retry waits,
  OpenAI translation chunks, FFmpeg audio analysis, and MKV merging.
- Added user-exported, redacted diagnostics with candidate decisions, retry
  history, timing metrics, API token usage, and local tool versions.
- Replaced first-run prompts with a readiness checklist for tools, API
  connection tests, media folders, mpv, and a first media workflow.
- Added a safe mpv configuration assistant with conflict detection, exact
  preview, isolated managed settings, timestamped backups, and restore.
- Added Economy, Balanced, and Best translation presets, editable advanced
  controls, official model prices, and per-media cost estimates.
- Added detailed timing diagnostics for median and p80 error, runtime coverage,
  local spread, timing jumps, and discontinuity rejection.
- Made Prepare scroll instead of compressing controls in smaller windows.
- Expanded all 29 translated catalogs to cover the new setup and safety UI.

## 0.9.0-beta.3

- Added automatic macOS interface-language detection and an independent
  interface-language preference.
- Added complete draft Qt catalogs for all 30 supported languages.
- Added right-to-left layouts for Arabic, Persian, Hebrew, and Urdu while
  preserving left-to-right technical fields.
- Added localized first-run setup, dependency guidance, safety confirmations,
  connection states, candidate review, and workflow summaries.
- Added catalog coverage, placeholder validation, compilation tooling, and
  localized quick-start guides.
- Fixed overlapping background jobs that could invalidate a running Qt thread.
- Fixed post-install tool discovery so Homebrew setup works without restarting.
- Hardened API retries, response limits, archive extraction, and SRT validation.
- Improved episode, year, Unicode-title, and sidecar-language candidate matching.
- Strengthened private folder scanning, settings writes, and merged-output checks.

## 0.9.0-beta.2

- Added a guided first-run Homebrew dependency setup.
- Added per-tool readiness checks for FFmpeg, FFprobe, MKVToolNix, and mpv.
- Added an explicit, visible Terminal install handoff with automatic rechecking.
- Expanded in-app mpv installation and dual-subtitle configuration guidance.

## 0.9.0-beta.1

- Rebuilt the interface with PySide6 around Prepare, Recent, and Settings
  workflows.
- Added 30 source and target language profiles.
- Added source-aware and target-aware editable translation prompts.
- Added configurable OpenAI model and reasoning controls.
- Generalized embedded and sidecar subtitle selection beyond one language pair.
- Generalized OpenSubtitles search, candidate review, and alternate retries.
- Added macOS Keychain credential storage and plaintext credential migration.
- Replaced fixed media paths with user-selected files and approved folders.
- Changed default output to sit beside the original while leaving source media
  untouched.
- Added optional workspace cleanup and verified move-to-Trash behavior.
- Standardized clean MKV output for dual subtitles in mpv.
- Added privacy, security, mpv setup, and API configuration documentation.
- Added native Apple Silicon and Intel build automation.
