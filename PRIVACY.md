# Privacy and distribution

Advisor mode contacts deadlock-api.com for catalogs, analytics, match discovery
and live broadcasts. Requests include the configured account or match ID,
hero IDs and query filters. Item artwork is fetched from catalog image URLs.
The app has no telemetry or automatic diagnostic upload.

Optional corner OCR reads only the match stamp from Deadlock's window, in memory.
It does not supply items, souls, damage or inventory. It saves no images. OCR is
off in a fresh install until enabled. Advice requires API roster verification.

Account ID, preferences and window position live in overlay_config.json beside
the executable when writable, or the user's local application-data folder.
API caches, downloaded icons and bounded logs live under
%LOCALAPPDATA%/DeadlockWPAOverlay. Logs are local and may contain identifiers
or paths when diagnosing a problem. Do not post them publicly without review.

The separate legacy Statlocker mode and explicit diagnostic commands can capture
images and read companion data. They are not used by Advisor mode. Public builds
do not include the proprietary companion heading template or game artwork.

Git ignores personal settings, logs, captures, caches, virtual environments,
recorded fixtures and assistant context files. Release packaging includes only
the executable and reviewed public documentation. Synthetic tests replace live
player recordings. The release checker inspects tracked paths before content,
and reports only file names for suspected sensitive content.

Never force-add private files. If credentials are accidentally published,
revoke them before addressing history.
