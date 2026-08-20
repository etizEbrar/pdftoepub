# PDF to EPUB — Support

> **Before publishing:** replace the `[BRACKETED]` placeholders. They are
> details only the app's owner can provide.

## How conversion works

You choose a PDF. The app checks it on your device, then sends it to the
conversion server, which rebuilds it as a reflowable EPUB3 ebook and sends it
back. Your file is deleted from the server once you have the result.

"Reflowable" is the point: unlike a PDF, the finished book re-wraps to your
screen, so you can change the font size and read comfortably on a phone.

The conversion is deterministic and local to the server — it does not use a
cloud AI service, and no part of your book is sent to an AI provider.

## What converts well

- Text-based PDFs — novels, non-fiction, reports, papers.
- Scanned books. Pages without a text layer are read with OCR.
- Books with footnotes and endnotes, which become tappable links.
- Tables, and simple equations, which become real MathML.
- Poetry and verse, which keep their line breaks.
- Right-to-left languages, including mixed-direction text.

## What converts poorly

- **Password-protected PDFs.** Remove the password first — the app cannot open
  them and will say so before uploading.
- **Heavily designed layouts** — magazines, cookbooks, children's picture books.
  Where a page's structure cannot be reconstructed safely, a faithful image of
  it is kept instead of a guess.
- **Poor-quality scans.** Faint, skewed or low-resolution pages produce weaker
  OCR. Where the text cannot be read confidently, the page is preserved as an
  image rather than filled with invented words.
- **Very large books.** There are limits on file size and page count; the app
  reports them if you hit one.

## Setting up the conversion server

This app converts using a server you point it at.

1. Open **Settings** in the app.
2. Enter the server's address.
3. Tap **Test connection** — it reports exactly what it found.

If you run the server on your own computer, use that computer's address on your
network, for example `http://192.168.1.10:8000`. On a real iPhone, `localhost`
means *the phone itself*, so it will not work. Both devices must be on the same
Wi-Fi network.

A server on the internet must use `https://` — the app will not send your
documents unencrypted across the internet.

## Troubleshooting

**"No conversion server set up"**
You have not entered an address yet. Open Settings and add one.

**"No server at that address"**
The address could not be resolved. Check it for a typo.

**"Can't reach the server" / "Nothing listening on that port"**
The address is right but nothing answered. Check the server is running, that the
port is correct, and that both devices are on the same network.

**"No network connection"**
The device itself is offline. Check Wi-Fi or mobile data.

**"The server stopped responding"**
The conversion took longer than expected. Very large books take longer; try
again, and if it recurs the server may be short of memory.

**"Use https:// …"**
You entered a plain `http://` address for a server on the internet. This is
refused deliberately: your document would cross the network unencrypted.

**"This PDF is locked"**
The PDF is password-protected. Remove the password and try again.

**"We can't read this PDF"**
The file is damaged, or is not really a PDF.

**"Not enough space"**
The device is too full to save the converted book. Free up space and retry.

**"Too many conversions started recently"**
The server limits how many conversions one client may start per hour. Wait and
try again.

**The conversion finished but the text has mistakes**
On scanned books, OCR is imperfect. The app reports how many pages needed OCR
and flags low-confidence results rather than hiding them. Where the text could
not be read confidently, the original page image is preserved instead of
guessed text.

## Your privacy

Your PDF is uploaded only to convert it, and is deleted afterwards. There are no
accounts, no tracking and no ads. The full technical detail is in
[privacy.md](privacy.md), and the policy is in
[privacy-policy.md](privacy-policy.md).

## Contact

[SUPPORT EMAIL]

When reporting a problem, it helps to include:

- what kind of PDF it was (text or scanned, roughly how many pages),
- what the app showed, word for word,
- what you expected instead.

Please do **not** send us the book itself unless we ask and you have the right
to share it.
