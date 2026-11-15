# Contributing

Use Windows 10/11 with Python 3.11. Create a virtual environment and install the
development dependencies listed in README.md. Run the full test suite before a PR.
Use synthetic API fixtures; never attach recordings, account settings or raw logs.

Keep source files below 500 lines and folders shallow. Put contracts in models.py,
keep modules specific to a domain, and add regression tests for safety changes.
Use ordinary hyphens rather than em dash punctuation. Follow AGENTS.md.

Purchase advice must remain reproducible through --explain. Queue stability must
never preserve an owned, stale, unsupported or otherwise invalid recommendation.
Missing API data means unknown, not a guessed value. Do not add handwritten
item-counter claims or unsupported discounts.

Build and release instructions live in README.md. Never include generated
personal settings in a ZIP. Report security problems privately, not by posting
credentials in public issues.
