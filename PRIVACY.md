# Privacy

SubtitleTranslator is designed without a developer-operated data service.

## Data the Developer Receives

None. The app contains no telemetry, analytics, advertising identifiers, crash
uploader, account system, remote logging, or developer-controlled API relay.

Opening the GitHub project or downloading a GitHub release is subject to
GitHub's own service policies. The running application does not automatically
contact GitHub.

## API Credentials

OpenAI and OpenSubtitles API keys are stored as generic passwords in macOS
Keychain under the service name:

```text
com.danielpberg.SubtitleTranslator
```

After an approved read, keys are held in memory for the remainder of that app
launch and used only for direct requests to the selected provider. They are not
written to the settings file, logs, job summaries, media files, subtitle files,
or diagnostics.

The app checks only Keychain item metadata during startup. A legacy plaintext
credential is removed automatically only after a matching Keychain item is
confirmed to exist, without reading either secret.

## Local Data

Non-secret preferences are stored at:

```text
~/Library/Application Support/SubtitleTranslator/settings.json
```

This includes the chosen interface language. Locale detection and catalog
loading are local; the interface language is not reported to the developer or
sent to an API provider. Settings can also contain exact paths for recent media
files and paths to media folders the user explicitly approved for recursive
scanning.

Intermediate subtitles, timing caches, and local job summaries default to:

```text
~/Library/Application Support/SubtitleTranslator/Workspace/
```

These locations are user-private by filesystem permissions. The workspace is
configurable and can be cleaned after successful processing.

Media files are read from locations selected by the user. Choosing an
individual file remembers only that exact path and does not approve its parent
folder. Recursive enumeration is limited to folders explicitly added by the
user. Originals are not changed unless the user explicitly enables **Move
original to Trash after verified merge** for a specific job.

## Network Requests

SubtitleTranslator talks directly to two optional third-party services:

### OpenAI

When translation is requested, OpenAI receives:

- The selected OpenAI API key in the authorization request.
- The source subtitle chunks.
- The composed translation instructions.
- The selected model and reasoning setting.

Translation requests set `store` to `false` so the Responses API is not asked
to retain response state. This does not replace OpenAI's own service, abuse
monitoring, or account data policies.

Media audio, video, unrelated files, local folder listings, and OpenSubtitles
credentials are not sent to OpenAI.

### OpenSubtitles

When subtitle search or download is requested, OpenSubtitles receives:

- The OpenSubtitles API key.
- A media hash and/or title query.
- The selected target language.
- A selected subtitle file identifier for download.

Media contents, subtitle text sent to OpenAI, local folder listings, and the
OpenAI key are not sent to OpenSubtitles.

Data retained by OpenAI and OpenSubtitles is governed by each provider's terms
and account settings.

## Logs

The app's visible details panel contains processing stages and error messages.
It does not intentionally log API keys, authorization headers, or subtitle
dialogue. Local job summaries use media filenames rather than full source paths.

Diagnostics are created in memory for each job and are written only when the
user chooses **Export Diagnostics**. An exported report can contain media
filenames, OpenSubtitles release labels and file identifiers, timing metrics,
candidate decisions, retry metadata, model and reasoning choices, API-reported
token counts, and local tool versions. It excludes API keys, authorization
headers, subtitle dialogue, and full media paths. Exported reports are written
with user-only file permissions.

Do not paste API keys into GitHub issues, screenshots, or shared diagnostics.

## Verification

The source is public so users can inspect the network endpoints, Keychain
storage, settings schema, and build workflow. Security reports should follow
[SECURITY.md](SECURITY.md).
