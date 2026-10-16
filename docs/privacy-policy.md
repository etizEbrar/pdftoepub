# Privacy Policy

**Last updated:** 2026-09-07
**Applies to:** the PDF to EPUB iOS application

> **Before publishing:** replace every `[BRACKETED]` placeholder. Those are
> facts only the app's owner can supply — they have deliberately not been
> invented. This document describes the software as built (see
> [`docs/privacy.md`](privacy.md) for the technical trace). It has **not** been
> reviewed by a lawyer, and it is not a compliance certification.

## Who is responsible

Safiye Ebrar Etiz ("we") operates the PDF to EPUB application.

Contact for privacy questions: safiyeebraretiz@gmail.com

## The short version

PDF to EPUB converts a PDF you choose into an EPUB ebook. To do that, the file
is sent to a conversion server, converted, and sent back. It is deleted
afterwards. We do not create an account for you, we do not track you, we do not
show ads, and we do not use your documents to train AI systems.

## What we process

**The PDF you choose.** When you start a conversion, the file is uploaded to the
conversion server over an encrypted connection (HTTPS). We process it only to
produce your EPUB.

**The EPUB that is produced.** It is sent back to your device and stored there.

**Basic technical information.** The conversion server, and the hosting provider
in front of it, record ordinary request information such as your IP address,
timestamps and request paths. This is used to operate the service and to limit
abuse — conversions are computationally expensive, so we count recent requests
per IP address.

**Nothing else.** There is no account, no name, no email address, no advertising
identifier, and no analytics or tracking SDK in the app.

## How long we keep your document

Your PDF and the EPUB made from it are deleted from the server as soon as the
app has downloaded the result — normally within seconds of the conversion
finishing.

If a conversion is abandoned (for example the app is closed mid-conversion), an
automatic cleanup removes the files and the associated record within
3 hours.

We do not keep copies, backups or archives of your documents beyond this.

## What we do not do with your documents

- We do not read them.
- We do not use them to train any AI or machine-learning system.
- We do not sell, rent or share them.
- We do not use them for advertising or profiling.

## Artificial intelligence

Almost all of the conversion is performed by deterministic software running on
the server: text extraction, optical character recognition, typography repair
and EPUB generation. Scanned pages are read on your own device using Apple's
Vision framework, and the page images never leave your phone.

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

## Who else receives your data

**Our hosting provider**, which runs the conversion server and necessarily
processes the traffic to it: Render (Render Services, Inc.), Frankfurt, Germany (EU).

Apple processes your download of the app itself, and any information you send
via TestFlight or App Store feedback, under Apple's own privacy policy. We do
not receive your documents through Apple.

We do not use any other processor, analytics service, advertising network or
data broker.

## Where your data is processed

The conversion server runs in Frankfurt, Germany (EU). If you are located elsewhere,
your document is transmitted to that region for the moments it takes to convert
it, and is then deleted.

## Security

Traffic between the app and the server is encrypted with HTTPS. The app refuses
to send your documents unencrypted to a server on the internet. Uploads are
size-limited, validated as PDFs, given random unguessable identifiers, and
stored only for the duration described above.

No system is perfectly secure, and we do not claim otherwise.

## Your rights

Because we hold no account and delete your documents automatically, there is
normally nothing of yours left for us to retrieve or erase by the time you would
ask.

Depending on where you live, you may have rights to access, correct, delete or
restrict the processing of personal data we hold about you, and to complain to
your data protection authority. To make a request, contact safiyeebraretiz@gmail.com.

> **Note on GDPR/CCPA:** this policy describes the software's actual behaviour.
> Whether the service meets the requirements of a particular regime depends on
> how and where you deploy it, and on legal review — neither of which this
> document can substitute for. No compliance claim is made here.

## Children

This app is not directed at children, and we do not knowingly collect personal
information from children. We do not ask any user their age, because we do not
collect personal information at all beyond what is described above. If you
believe a child has sent us information, contact safiyeebraretiz@gmail.com.

## Cookies and web technologies

The iOS app does not use cookies, web beacons, or similar tracking technologies.
The conversion server is an API consumed by the app; it does not set cookies and
serves no advertising or tracking scripts.

[If you publish this policy on a website, describe that site's own cookie use
here — this section covers the app and the API only.]

## Changes to this policy

If this policy changes materially we will update this page and the "last
updated" date above.

## Contact

Safiye Ebrar Etiz
safiyeebraretiz@gmail.com
https://etizebrar.github.io/pdftoepub
