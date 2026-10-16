# Draft: privacy disclosure for structural review

**Not published.** `scripts/build-site.py` renders only `privacy-policy.md` and
`support.md`, so nothing in `docs/drafts/` reaches the site.

This replaces the "Artificial intelligence" section of the privacy policy on the
day structural review is offered on the app's own server -- and not before.
Three things have to ship together with it, or the app is out of line with App
Review Guideline 5.1.2(i), which requires explicit permission before personal
data is shared with a third-party AI:

1. An in-app opt-in, off by default, that says what would be sent before the
   reader agrees. A server-side switch alone is not permission.
2. The App Privacy answers in App Store Connect updated to match.
3. The review notes updated to describe the opt-in and how to test it.

It was briefly the published wording for 1.0.1 and was withdrawn before release
for exactly that reason: it described a flow the app had no consent step for.

---

## Artificial intelligence

Almost all of the conversion is performed by deterministic software running on
the server: text extraction, optical character recognition, typography repair
and EPUB generation. Scanned pages are read on your own device using Apple's
Vision framework, so the server does not run text recognition on them. The PDF
itself, scanned pages included, is still uploaded so the server can build your
EPUB, and is deleted afterwards as described above.

A small part of the work cannot be decided that way. Reconstructing a book
means deciding what each fragment of it *is* — a chapter title, a caption, a
footnote, a line of verse. On a typeset page the geometry usually settles
that. On a scanned page it often does not, because the type sizes carry almost
no signal. Measured on a real 168-page book, about **9% of fragments** fall
below the confidence threshold our own software can resolve.

**When structural review is enabled**, only those fragments are sent to
Anthropic's Claude API to be classified. Specifically:

- **What is sent:** the uncertain fragment and the lines immediately either
  side of it, each capped at a few hundred characters.
- **What is never sent:** the PDF itself, whole pages, images of your pages,
  the complete document, your name, your email, or any identifier. There is no
  account to attach anything to.
- **What comes back:** a structural label and a heading level. The request
  instructs the model never to rewrite, correct, translate, complete or
  summarise any text, and nothing it returns can change the author's words.
- **If the call fails:** our own answer stands and the conversion completes.

Anthropic does not train its models on data submitted through its API. We do
not use your documents to train anything either.

**The app always shows which provider the server is using.** Open Settings and
tap Test connection: it reports `none` when no cloud review is in use, and
`anthropic` when it is. That indicator is the authoritative answer for the
service you are connected to at that moment.

If you run the conversion server yourself, structural review is off unless you
configure it, and the software requires no API key and no paid service to work.

This policy is updated before any change to this behaviour takes effect.

