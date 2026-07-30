# Security

## Supported Version

The newest GitHub beta release receives security fixes. Earlier beta builds
should be considered unsupported.

## Reporting a Vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open a
public issue for a vulnerability involving credentials, private file access, or
request data.

Include:

- SubtitleTranslator version and Mac architecture.
- macOS version.
- Reproduction steps using placeholder credentials and non-sensitive files.
- Expected and observed behavior.

Never include a real API key, subtitle dialogue, private filename, or full local
path. Rotate any key that may have been exposed before submitting a report.

## Security Boundaries

- API credentials belong in macOS Keychain.
- Settings and job summaries must remain secret-free.
- The app must not add developer telemetry or a request relay.
- Folder enumeration must remain limited to user-approved locations.
- Source media must not be removed before a replacement passes mux and duration
  verification.
- Shell commands must use direct argument arrays rather than interpolated shell
  strings.

Unsigned beta artifacts cannot provide the same publisher identity guarantee as
a Developer ID-notarized build. Verify release checksums and use the artifact
matching the Mac architecture.
