# Landing page

Three files, no build step, no dependencies: `index.html`, `style.css`,
`main.js`. Open `index.html` directly or serve the folder.

Kept out of `site/`, which is **generated** from `docs/` by
`scripts/build-site.py` — anything written there by hand is destroyed the next
time that script runs.

## Before this goes public

Four placeholders, each marked with a `TODO` comment in `index.html`:

| What | Where | Note |
|---|---|---|
| App Store link | hero + final CTA | Version 1.0 is in review. The CTA deliberately says "Try it free" / "Join the beta" rather than "Download on the App Store", because a dead store badge is worse than an honest beta link. |
| TestFlight link | `data-cta="testflight"` | Paste the public beta URL. |
| `og:image` | `<head>` | Wants a real 1200×630 PNG. A missing one renders as an empty card, not a default. |
| Legal links | footer | Point at `../site/privacy.html` and `../site/support.html`. If this folder is deployed at the domain root instead, make them absolute. |

## Why the copy reads the way it does

The page is written to be checkable, because it is aimed at Anthropic.
Every number on it was measured on this repository and can be reproduced:

- **2.1 s/page** on-device OCR, against **110 s/page** server-side — the
  figures behind the Apple Vision work.
- **472** backend tests, the count at the time of writing.
- **EPUBCheck 5.3.0**, the version pinned in `backend/Dockerfile`.
- **claude-haiku-4-5**, the default model in `app/pipeline/ai/anthropic_provider.py`.

Claude's role is described as what the code actually does: an **opt-in**
reviewer that classifies the structural role of fragments the deterministic
pass scored below its confidence threshold, bounded to the fragment and its
immediate neighbours, forbidden by its own system prompt from rewriting any
text, and with the deterministic answer as the fallback when it fails.

It is **not** described as repairing typography, resolving hyphenation or
reconstructing reading order. Those are deterministic local code
(`textrepair.py`, `hyphenation.py`, `reading_order.py`) and run with
`AI_PROVIDER=none`, which is the production default and what the App Store
review notes state.

## Accessibility

`--ink-faint` and the light `--accent` are set to the lightest/darkest value
that still clears WCAG AA 4.5:1 against every surface they appear on, because
all of them carry small text. Measured ratios, dark then light:

    ink        16.50 / 16.00
    ink-dim     8.22 /  7.26
    ink-faint   4.63 /  4.57
    accent      5.41 /  4.56

Adjusting those three tokens for looks will break it.
