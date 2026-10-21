# Conversion audit

Tests prove that the cases we already know about stay fixed. The audit finds
the ones we do not know about yet, by converting real books of many kinds and
counting what a reader would notice.

```sh
cd backend
.venv/bin/python scripts/corpus/fetch.py            # once: downloads the books in sources.json
.venv/bin/python scripts/corpus/audit.py --compare  # before every change goes out
```

`--compare` exits non-zero when any book got worse than `baseline.json`:
a defect count up by two and ten percent, EPUBCheck newly failing, or memory
near the server's 512 MB. After a change that makes things better, record the
new state with `--save-baseline` and commit `baseline.json` with the change.

Extra PDFs can be audited alongside the corpus without being added to it:

```sh
.venv/bin/python scripts/corpus/audit.py ~/Downloads/some-book.pdf
```

Each book is converted in its own process, as the server converts it. The
EPUBs and per-book reports land in `backend/corpus/audit/` (git-ignored), so a
defect can be opened and read, not just counted.

## What is counted

Per 1,000 words, so a long book and a short one compare:

| | |
|---|---|
| broken | a paragraph cut mid-sentence: the next one opens in lowercase |
| hyphen | a word left broken at a line join ("keli- me") |
| junk | a paragraph of stray marks, a lone letter, an ornament read as text |
| furniture | a running head or page number left in the text |
| ocr | a word with a digit or a stray mark inside it ("BİL6İ5AYAR") |
| glued | two words run together ("şekildetezgâha") |
| split | a lowercase letter standing alone ("ya d a") |
| chars | replacement characters, private-use glyphs, soft hyphens |
| headings | a heading that is a bare number, starts lowercase or is a sentence |
| pictures | an image of a whole page, other than the cover |

Some counts are noise for some books and are read with that in mind: a
mathematics paper's single-letter variables count as "split", and a
linguistics article citing the stem "çök-" counts as "hyphen".

## Adding a book

Add an entry to `sources.json` naming the layout it stands for. Only
public-domain, openly licensed or open-access PDFs, at most 25 MB (the
server's upload limit). Arabic-script Ottoman scans were tried and left out:
their OCR layers are Latin-script guesses and nothing the app can read.
