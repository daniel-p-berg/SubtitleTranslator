"""Verified HTTPS context backed by a certificate bundle shipped with the app."""

from __future__ import annotations

import ssl
from functools import lru_cache
from pathlib import Path

import certifi


def ca_bundle_path() -> Path:
    """Return the bundled Mozilla CA file or fail before making a request."""
    path = Path(certifi.where())
    if not path.is_file():
        raise RuntimeError(
            "SubtitleTranslator's trusted certificate bundle is missing."
        )
    return path


@lru_cache(maxsize=1)
def verified_ssl_context() -> ssl.SSLContext:
    """Return a reusable context with hostname and certificate checks enabled."""
    context = ssl.create_default_context(cafile=str(ca_bundle_path()))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
