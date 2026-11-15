# Agent Rules

These are non-negotiable. When in doubt, follow the stricter reading.

## 1. Secrets are radioactive: never view them
- Never read, open, or pull into context any file that holds secrets
  (`.env`, `auth.json`, credentials, tokens, API keys, passwords, private keys).
- Never echo, log, summarize, or return a secret value, not even to the owner.
- When a task must touch a secret, operate on it programmatically so the value
  never passes through model tokens.
- Listing a file's name, size, or existence is allowed; reading contents is not.

## 2. Never leak via side channels
- Check diffs before committing; a secret or private file must never land in a
  commit, log, screenshot, paste, or report.
- Redact or omit secret/private material from every artifact produced.

## 3. Least-privilege reads
- Do not read private or personal files unless the task strictly requires it.
- Prefer structural inspection (names, sizes, schemas, keys) over content.
- Treat unknown files as secret by default.

## 4. Verify before irreversible actions
- No destructive or hard-to-undo actions (`git push`, reset/force, `rm -rf`,
  deploys, data deletion) without explicit approval.
- Show the command before running it; prefer reversible steps.

## 5. Ask before substantial downloads or system changes
- Ask first for downloads of 500 MB or more, system-wide installs, large model
  pulls, or system config changes.
- Small downloads clearly implied by the task (normal package installs) are fine.
- Ephemeral tool hygiene: delete temporary tools, decompilers, and one-off
  scripts when the task is finished.

## 6. AI conversation privacy
- Never check, view, read, parse, or log conversations, transcripts, history, or
  session files of any AI tool, especially local ones (LM Studio, Ollama, Jan).
- Never inspect them even for debugging or inferring configuration. Ask instead.

## 7. Typography: never emit em-dashes
- No em-dashes (U+2014) in copy, docs, titles, UI labels, or code comments.
- Use hyphens for ranges, colons or slashes for subtitles, commas for pauses.

## 8. Agent-friendly architecture
- Source files strictly under 500 lines, target 150-300. Split at around 400.
- Shallow folders (max 3-4 levels), domain-first modules, single responsibility.
- No grab-bag files (`utils.py`, `helpers.ts`, `common.js`, `misc.py`).
- Contracts and types defined up front (`models.py`, `ARCHITECTURE.md`).
- Functions under 40-50 lines where practical, pure where possible.
- Tests mirror modules under `tests/`; one command runs them:
  `.venv/Scripts/python -m pytest tests/ -q`

## Current state
- All source files are under 500 lines. Statlocker counters live in
  `statlocker_counters.py`, WPA card building in `wpa_item_builder.py`, and
  overlay rendering in `ui/overlay_render.py`.
- The overlay unit tests create Tk windows without the background worker;
  starting many Python threads while Tk tears down crashes CPython 3.11 on
  Windows. Production still starts the worker by default.
