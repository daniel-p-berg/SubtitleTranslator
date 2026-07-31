#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="SubtitleTranslator"
VERSION="${VERSION:-0.9.0-beta.13}"
PYTHON="${PYTHON:-python3.12}"
ARCH="$(uname -m)"
TARGET_ARCH="${TARGET_ARCH:-$ARCH}"
ARTIFACT_ARCH="${ARTIFACT_ARCH:-$TARGET_ARCH}"
ARTIFACT_DIR="$SCRIPT_DIR/release"
LICENSE_DIR="$SCRIPT_DIR/.build-licenses"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
blue() { printf "\033[34m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

download_license() {
    local url="$1"
    local checksum="$2"
    local destination="$3"
    local temporary="${destination}.download"

    curl --fail --location --silent --show-error "$url" --output "$temporary"
    local actual
    actual="$(shasum -a 256 "$temporary" | awk '{print $1}')"
    if [[ "$actual" != "$checksum" ]]; then
        rm -f "$temporary"
        printf "License checksum mismatch for %s.\n" "$url" >&2
        exit 1
    fi
    mv "$temporary" "$destination"
}

verify_bundle_architectures() {
    local app_path="$1"
    local required_arches=("$TARGET_ARCH")
    if [[ "$TARGET_ARCH" == "universal2" ]]; then
        required_arches=(arm64 x86_64)
    fi

    while IFS= read -r -d '' candidate; do
        if [[ "$(file -b "$candidate")" == *"Mach-O"* ]]; then
            lipo "$candidate" -verify_arch "${required_arches[@]}"
        fi
    done < <(find "$app_path" -type f -print0)
}

blue "Checking Python and build dependencies..."
"$PYTHON" --version
"$PYTHON" -m pip install --upgrade "pip>=26.1.2" --break-system-packages
"$PYTHON" -m pip install -r requirements-dev.txt --break-system-packages

blue "Preparing third-party license notices..."
mkdir -p "$LICENSE_DIR"
download_license \
    "https://www.gnu.org/licenses/gpl-3.0.txt" \
    "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986" \
    "$LICENSE_DIR/GPL-3.0.txt"
download_license \
    "https://www.gnu.org/licenses/lgpl-3.0.txt" \
    "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118" \
    "$LICENSE_DIR/LGPL-3.0.txt"
download_license \
    "https://raw.githubusercontent.com/python/cpython/v3.13.13/LICENSE" \
    "78b12c3a81360b357002334f0e70ea0e92eebf7a9b358805c03c48484945f3bb" \
    "$LICENSE_DIR/PYTHON-LICENSE.txt"
"$PYTHON" -m piplicenses \
    --format=plain-vertical \
    --with-license-file \
    --no-license-path \
    > "$LICENSE_DIR/PYTHON-PACKAGES.txt"

blue "Running source and test checks..."
"$PYTHON" -m ruff check . --select F
"$PYTHON" tools/build_translations.py --check
"$PYTHON" tools/build_translations.py --compile
"$PYTHON" -m py_compile \
    app_paths.py \
    audio_activity.py \
    chunker.py \
    dependencies.py \
    extractor.py \
    i18n.py \
    languages.py \
    main.py \
    media_launcher.py \
    muxer.py \
    open_subtitles.py \
    pipeline.py \
    settings.py \
    subtitle_sync.py \
    translator.py \
    ui.py \
    tools/build_translations.py \
    tools/generate_draft_translations.py \
    tools/generate_localized_guides.py
"$PYTHON" test_pipeline.py
"$PYTHON" -m unittest -v test_product.py

blue "Building ${APP_NAME}.app for ${TARGET_ARCH}..."
rm -rf build dist
"$PYTHON" -m PyInstaller --noconfirm --clean SubtitleTranslator.spec

APP_PATH="$SCRIPT_DIR/dist/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
    printf "Build failed: %s was not created.\n" "$APP_PATH" >&2
    exit 1
fi

blue "Verifying bundled architectures..."
verify_bundle_architectures "$APP_PATH"

blue "Applying an ad-hoc signature..."
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"

blue "Smoke-testing the packaged application..."
SUBTITLE_TRANSLATOR_SMOKE_TEST=1 \
QT_QPA_PLATFORM=offscreen \
"$APP_PATH/Contents/MacOS/$APP_NAME"

blue "Creating release archives..."
mkdir -p "$ARTIFACT_DIR"
ZIP_NAME="${APP_NAME}-${VERSION}-macOS-${ARTIFACT_ARCH}.zip"
DMG_NAME="${APP_NAME}-${VERSION}-macOS-${ARTIFACT_ARCH}.dmg"
ZIP_PATH="$ARTIFACT_DIR/$ZIP_NAME"
DMG_PATH="$ARTIFACT_DIR/$DMG_NAME"
rm -f "$ZIP_PATH" "$DMG_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"

DMG_ROOT="$SCRIPT_DIR/build/dmg-root"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
ditto "$APP_PATH" "$DMG_ROOT/${APP_NAME}.app"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_ROOT" \
    -ov \
    -format UDZO \
    "$DMG_PATH" >/dev/null

(
    cd "$ARTIFACT_DIR"
    shasum -a 256 "$ZIP_NAME" "$DMG_NAME"
) > "$ARTIFACT_DIR/SHA256SUMS-${ARTIFACT_ARCH}.txt"

green "Built:"
green "  $ZIP_PATH"
green "  $DMG_PATH"
yellow "This beta is not notarized. Use Privacy & Security > Open Anyway once."
