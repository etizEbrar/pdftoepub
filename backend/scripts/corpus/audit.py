"""Convert every book in the corpus and measure what a reader would notice.

A conversion that completes and passes EPUBCheck can still read badly, and
until now that was only found when a reader sent a screenshot. This reads the
EPUB the way a reader does and counts the defects every bad conversion so far
has shown, none of them specific to one book:

  broken      a paragraph cut mid-sentence: the next one opens in lowercase
  hyphen      a word left broken at a line join ("keli- me")
  junk        a paragraph of stray marks, a lone letter, an ornament read as text
  furniture   a running head or page number left in the text
  ocr         a word with a digit or a stray mark inside it ("BİL6İ5AYAR")
  glued       two words run together ("şekildetezgâha")
  split       a word broken by a space ("ya d a")
  chars       replacement characters, private-use glyphs, soft hyphens
  headings    a heading that is a bare number, starts lowercase or is a sentence
  pictures    an image of a whole page, other than the cover

Each is reported per 1,000 words, so a long book and a short one compare.

    .venv/bin/python scripts/corpus/audit.py                  # whole corpus
    .venv/bin/python scripts/corpus/audit.py extra.pdf ...    # plus other books
    .venv/bin/python scripts/corpus/audit.py --save-baseline  # record the result
    .venv/bin/python scripts/corpus/audit.py --compare        # fail on regressions

Every book is converted in a process of its own, as the server converts it,
and its peak memory is reported against the server's 512 MB.
"""

from __future__ import annotations

import argparse
import json
import re
import resource
import subprocess
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
CORPUS = BACKEND / "corpus"
BASELINE = HERE / "baseline.json"
RESULTS = CORPUS / "audit"

DEFECTS = ("broken", "hyphen", "junk", "furniture", "ocr", "glued", "split", "chars", "headings", "pictures")
# How much each defect costs a reader, for ranking books worst first.
WEIGHTS = {
    "broken": 3, "hyphen": 1, "junk": 2, "furniture": 3, "ocr": 1,
    "glued": 1, "split": 1, "chars": 2, "headings": 3, "pictures": 5,
}
MEMORY_LIMIT_MB = 512

_NS = {"x": "http://www.w3.org/1999/xhtml"}
_WORD = re.compile(r"[^\W\d_]+(?:[’'][^\W\d_]+)?")
_TOKEN = re.compile(r"\S+")
# A letter, then a digit or a stray mark, then a letter: never a real word.
_OCR_WORD = re.compile(r"[^\W\d_][\d^<>|\\~]+[^\W\d_]")
_GLUED = re.compile(r"[a-zçğıöşü]{3,}[A-ZÇĞİÖŞÜ][a-zçğıöşü]{2,}")
_HYPHEN_BREAK = re.compile(r"[^\W\d_]{2,}- [a-zçğıöşü]{2,}")
_FOLIO = re.compile(r"^[\W_]*\d{1,4}[\W_]*$")
_BAD_CHARS = re.compile("[�-­\x00-\x08\x0b\x0c\x0e-\x1f]")
# Single letters that are words in the corpus's languages.
_LETTER_WORDS = {"a", "o", "e", "i", "I", "O", "A", "E", "y"}


def _text(element) -> str:
    return " ".join("".join(element.itertext()).split())


def _body_nodes(root):
    """Text a reader reads, in order: paragraphs, list items, headings."""
    return root.xpath(
        "//x:body//*[self::x:p or self::x:li or self::x:h1 or self::x:h2 or self::x:h3 or self::x:h4]"
        "[not(ancestor::x:aside)][not(ancestor::x:table)][not(ancestor::x:nav)][not(ancestor::x:li)]",
        namespaces=_NS,
    )


def measure_epub(path: Path, page_aspect: float | None) -> dict:
    from lxml import etree

    counts = Counter()
    examples: dict[str, list[str]] = {name: [] for name in DEFECTS}
    words = 0
    lines = Counter()
    paragraphs = headings = blockquotes = list_items = 0

    def note(kind: str, sample: str) -> None:
        counts[kind] += 1
        if len(examples[kind]) < 6:
            examples[kind].append(sample[:120])

    with zipfile.ZipFile(path) as epub:
        names = sorted(n for n in epub.namelist() if n.startswith("OEBPS/text/"))
        chapters = len(names)
        for name in names:
            root = etree.fromstring(epub.read(name))
            blockquotes += len(root.xpath("//x:blockquote", namespaces=_NS))
            previous = None
            for node in _body_nodes(root):
                tag = etree.QName(node).localname
                text = _text(node)
                if not text:
                    continue
                words += len(_WORD.findall(text))
                if tag.startswith("h"):
                    headings += 1
                    if _FOLIO.match(text) or text[0].islower() or len(text.split()) > 20:
                        note("headings", text)
                    previous = None
                    continue
                if tag == "li":
                    list_items += 1
                else:
                    paragraphs += 1
                cls = node.get("class") or ""
                if len(text) <= 60:
                    lines[text.casefold()] += 1
                if _FOLIO.match(text):
                    note("furniture", text)
                elif sum(c.isalpha() for c in text) <= 2 or (
                    len(text) <= 25 and sum(c.isalpha() for c in text) < len(text.replace(" ", "")) * 0.5
                ):
                    note("junk", text)
                if (
                    previous is not None
                    and "toc-entry" not in cls
                    and text[0].islower()
                    and not previous.rstrip().endswith(":")
                ):
                    note("broken", f"…{previous[-50:]} ‖ {text[:50]}")
                for match in _OCR_WORD.finditer(text):
                    note("ocr", match.group(0))
                for match in _GLUED.finditer(text):
                    note("glued", match.group(0))
                for match in _HYPHEN_BREAK.finditer(text):
                    note("hyphen", match.group(0))
                for match in _BAD_CHARS.finditer(text):
                    note("chars", f"U+{ord(match.group(0)):04X} in …{text[max(0, match.start() - 20):match.start() + 20]}")
                tokens = _TOKEN.findall(text)
                for i, token in enumerate(tokens):
                    core = token.strip(".,;:!?\"'“”‘’()[]«»…-–—")
                    # A capital alone is an initial or a variable ("John H.
                    # Watson", "model G"); a lowercase letter alone is a word
                    # a space was put into.
                    if len(core) == 1 and core.isalpha() and core.islower() and core not in _LETTER_WORDS:
                        note("split", " ".join(tokens[max(0, i - 2) : i + 3]))
                previous = text if tag == "p" else None

        for line, seen in lines.items():
            if seen >= 4 and len(line) >= 4 and not _FOLIO.match(line):
                counts["furniture"] += seen - 1
                if len(examples["furniture"]) < 6:
                    examples["furniture"].append(f"{line[:60]} ×{seen}")

        pictures = [n for n in epub.namelist() if n.startswith("OEBPS/images/")]
        opf = epub.read("OEBPS/content.opf").decode("utf-8")
        cover = re.search(r'href="images/([^"]+)"[^>]*properties="cover-image"', opf)
        if page_aspect:
            import fitz

            for name in pictures:
                if cover and name.endswith(cover.group(1)):
                    continue
                try:
                    pix = fitz.Pixmap(epub.read(name))
                except Exception:
                    continue
                if pix.width * pix.height > 600_000 and abs(pix.width / pix.height - page_aspect) < page_aspect * 0.04:
                    note("pictures", name)

    per_thousand = {k: round(counts[k] * 1000 / max(words, 1), 2) for k in DEFECTS}
    return {
        "words": words,
        "chapters": chapters,
        "paragraphs": paragraphs,
        "headings": headings,
        "list_items": list_items,
        "blockquotes": blockquotes,
        "images": len(pictures),
        "has_cover": bool(cover),
        "counts": {k: counts[k] for k in DEFECTS},
        "per_1000_words": per_thousand,
        "defect_index": round(sum(per_thousand[k] * WEIGHTS[k] for k in DEFECTS), 2),
        "examples": {k: v for k, v in examples.items() if v},
    }


def convert_one(pdf: Path, out: Path) -> None:
    """Child process: convert one book the way the server does, then measure it."""
    sys.path.insert(0, str(BACKEND))
    import fitz

    from app.jobs import store
    from app.models.job import ConversionMode, Job, JobStage
    from app.pipeline.orchestrator import _run_pipeline_sync

    with fitz.open(str(pdf)) as doc:
        rect = doc[0].rect if doc.page_count else None
        page_aspect = (rect.width / rect.height) if rect and rect.height else None
    job_id = "audit-" + re.sub(r"[^a-z0-9]+", "-", pdf.stem.lower())[:40]
    job = Job(job_id=job_id, source_filename=pdf.name, mode=ConversionMode.MAXIMUM_ACCURACY, upload_path=str(pdf))
    store.save_job(job)
    started = time.time()
    result: dict = {"book": pdf.stem}
    try:
        _run_pipeline_sync(job)
        result["seconds"] = round(time.time() - started, 1)
        result["stage"] = job.stage.value
        if job.stage == JobStage.COMPLETED:
            report = job.quality_report
            result.update(
                pages=report.page_count,
                epubcheck=report.epubcheck_passed,
                integrity=report.content_integrity_ratio,
                ocr_pages=report.ocr_page_count,
                needs_review=report.needs_review,
            )
            epub_copy = RESULTS / f"{pdf.stem}.epub"
            epub_copy.write_bytes(Path(job.epub_path).read_bytes())
            result.update(measure_epub(epub_copy, page_aspect))
        else:
            result["error"] = f"{job.error_code}: {job.error_message}"
    finally:
        store.delete_job(job_id)
    # ru_maxrss is bytes on macOS and kilobytes on Linux.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    result["peak_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))


def _run(pdf: Path) -> dict:
    out = RESULTS / f"{pdf.stem}.json"
    out.unlink(missing_ok=True)
    proc = subprocess.run(
        [sys.executable, __file__, "--one", str(pdf), str(out)],
        capture_output=True,
        text=True,
        cwd=BACKEND,
    )
    if not out.exists():
        return {"book": pdf.stem, "stage": "CRASHED", "error": proc.stderr.strip()[-600:]}
    return json.loads(out.read_text())


def _table(results: list[dict]) -> str:
    head = f"{'book':34s} {'pages':>5s} {'sec':>6s} {'MB':>5s} {'index':>6s}  " + " ".join(f"{k[:6]:>6s}" for k in DEFECTS)
    rows = [head, "-" * len(head)]
    for r in sorted(results, key=lambda r: -r.get("defect_index", 1e9)):
        if "per_1000_words" not in r:
            rows.append(f"{r['book']:34s} {r.get('stage')}: {r.get('error', '')[:80]}")
            continue
        rows.append(
            f"{r['book'][:34]:34s} {r.get('pages', 0):5d} {r.get('seconds', 0):6.0f} {r.get('peak_mb', 0):5} {r['defect_index']:6.1f}  "
            + " ".join(f"{r['per_1000_words'][k]:6.2f}" for k in DEFECTS)
        )
    return "\n".join(rows)


def _regressions(results: list[dict], baseline: dict) -> list[str]:
    found = []
    for r in results:
        before = baseline.get(r["book"])
        if not before:
            continue
        if "counts" not in r:
            found.append(f"{r['book']}: now {r.get('stage')} ({r.get('error', '')[:80]})")
            continue
        for key in DEFECTS:
            now, was = r["counts"][key], before["counts"].get(key, 0)
            # Small books move by a defect or two on any change; flag what a
            # reader would see, not noise.
            if now > was and now - was >= max(2, was * 0.1):
                found.append(f"{r['book']}: {key} {was} -> {now}")
        if before.get("epubcheck") and not r.get("epubcheck"):
            found.append(f"{r['book']}: EPUBCheck now fails")
        if r.get("peak_mb", 0) > MEMORY_LIMIT_MB * 0.9:
            found.append(f"{r['book']}: peak memory {r['peak_mb']} MB near the {MEMORY_LIMIT_MB} MB limit")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("books", nargs="*", type=Path, help="extra PDFs to audit")
    parser.add_argument("--only", help="audit only corpus books whose name contains this")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--one", nargs=2, type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.one:
        convert_one(*args.one)
        return 0

    RESULTS.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(CORPUS.glob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if args.only in p.stem]
    pdfs += [p.resolve() for p in args.books]
    if not pdfs:
        print("No books. Fetch the corpus first: scripts/corpus/fetch.py")
        return 1

    results = []
    for pdf in pdfs:
        print(f"converting {pdf.stem} …", flush=True)
        results.append(_run(pdf))
    (RESULTS / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print()
    print(_table(results))

    worst = {}
    for r in results:
        for kind, samples in r.get("examples", {}).items():
            worst.setdefault(kind, []).extend(f"[{r['book']}] {s}" for s in samples[:2])
    print("\nexamples:")
    for kind in DEFECTS:
        for sample in worst.get(kind, [])[:6]:
            print(f"  {kind:9s} {sample}")

    corpus_results = [r for r in results if (CORPUS / f"{r['book']}.pdf").exists()]
    if args.save_baseline:
        BASELINE.write_text(
            json.dumps(
                {r["book"]: {k: r[k] for k in ("counts", "epubcheck", "words") if k in r} for r in corpus_results},
                ensure_ascii=False,
                indent=1,
                sort_keys=True,
            )
            + "\n"
        )
        print(f"\nbaseline saved: {BASELINE}")
    if args.compare:
        if not BASELINE.exists():
            print("no baseline yet: run with --save-baseline first")
            return 1
        found = _regressions(corpus_results, json.loads(BASELINE.read_text()))
        print("\nregressions:" if found else "\nno regressions against the baseline")
        for line in found:
            print(f"  {line}")
        return 1 if found else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
