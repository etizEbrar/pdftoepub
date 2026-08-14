from __future__ import annotations

import csv
import functools
import io
import os
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TESSERACT_TIMEOUT_SECONDS = 180

# Common tessdata locations, checked when TESSDATA_PREFIX isn't already set.
_TESSDATA_CANDIDATES = (
    "/opt/homebrew/share/tessdata",
    "/usr/local/share/tessdata",
    "/usr/share/tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
)


@dataclass
class OCRWord:
    """One Tesseract word with its confidence, in *image pixel* coordinates."""

    text: str
    left: float
    top: float
    width: float
    height: float
    confidence: float
    block_num: int
    par_num: int
    line_num: int
    word_num: int

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)


@dataclass
class OCRResult:
    words: list[OCRWord] = field(default_factory=list)
    rotation: int = 0

    @property
    def mean_confidence(self) -> float:
        if not self.words:
            return 0.0
        return sum(w.confidence for w in self.words) / len(self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@functools.lru_cache(maxsize=1)
def tesseract_available() -> bool:
    return shutil.which(settings.tesseract_binary) is not None


@functools.lru_cache(maxsize=1)
def _tessdata_env() -> dict[str, str]:
    """Environment for Tesseract subprocesses, with TESSDATA_PREFIX resolved.

    Homebrew installs language data outside Tesseract's compiled-in default on
    some setups, so we point at it explicitly rather than depending on the
    caller having exported it.
    """
    env = dict(os.environ)
    if settings.tessdata_prefix:
        env["TESSDATA_PREFIX"] = settings.tessdata_prefix
        return env
    if "TESSDATA_PREFIX" in env:
        return env
    for candidate in _TESSDATA_CANDIDATES:
        if Path(candidate).is_dir():
            env["TESSDATA_PREFIX"] = candidate
            break
    return env


@functools.lru_cache(maxsize=1)
def available_languages() -> frozenset[str]:
    if not tesseract_available():
        return frozenset()
    try:
        proc = subprocess.run(
            [settings.tesseract_binary, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_tessdata_env(),
        )
    except (subprocess.SubprocessError, OSError):
        return frozenset()
    langs = {line.strip() for line in proc.stdout.splitlines()[1:] if line.strip()}
    return frozenset(langs)


def resolve_languages(requested: str) -> str:
    """Drop language codes this Tesseract install doesn't have, so one missing
    pack degrades to the languages that *are* present rather than failing the
    whole page."""
    available = available_languages()
    if not available:
        return requested
    wanted = [code for code in requested.split("+") if code]
    usable = [code for code in wanted if code in available]
    missing = [code for code in wanted if code not in available]
    if missing:
        logger.warning("OCR language pack(s) not installed, ignoring: %s", ", ".join(missing))
    if not usable:
        usable = ["eng"] if "eng" in available else [sorted(available)[0]]
    return "+".join(usable)


def _run_tesseract(image_path: Path, args: list[str]) -> str:
    cmd = [settings.tesseract_binary, str(image_path), "stdout", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TESSERACT_TIMEOUT_SECONDS,
            env=_tessdata_env(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("tesseract timed out on %s", image_path.name)
        return ""
    except OSError as exc:
        logger.warning("tesseract could not be run: %s", exc)
        return ""
    if proc.returncode != 0:
        logger.warning("tesseract exited %d: %s", proc.returncode, proc.stderr.strip()[:200])
        return ""
    return proc.stdout


def _normalize(text: str) -> str:
    """NFC-normalize and strip control characters. Tesseract can emit combining
    sequences and stray control codes that would otherwise reach the XHTML."""
    normalized = unicodedata.normalize("NFC", text)
    return "".join(ch for ch in normalized if ch == "\n" or unicodedata.category(ch)[0] != "C")


def run_ocr(image_path: Path, languages: str | None = None, psm: int = 3) -> OCRResult:
    """OCR an image and return words with real per-word Tesseract confidences.

    Words below `settings.ocr_min_word_confidence` are dropped rather than
    trusted — the pipeline must never present low-confidence OCR as fact.
    """
    if not tesseract_available():
        logger.warning("tesseract is not installed; cannot OCR %s", image_path.name)
        return OCRResult()

    lang = resolve_languages(languages or settings.ocr_languages)
    output = _run_tesseract(image_path, ["-l", lang, "--psm", str(psm), "tsv"])
    if not output.strip():
        return OCRResult()

    words: list[OCRWord] = []
    reader = csv.DictReader(io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        try:
            if int(row.get("level") or 0) != 5:  # level 5 == word
                continue
            text = _normalize((row.get("text") or "").strip())
            if not text:
                continue
            confidence = float(row.get("conf") or -1)
            if confidence < settings.ocr_min_word_confidence:
                continue
            words.append(
                OCRWord(
                    text=text,
                    left=float(row["left"]),
                    top=float(row["top"]),
                    width=float(row["width"]),
                    height=float(row["height"]),
                    confidence=confidence,
                    block_num=int(row["block_num"]),
                    par_num=int(row["par_num"]),
                    line_num=int(row["line_num"]),
                    word_num=int(row["word_num"]),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue  # a malformed TSV row is skipped, never guessed at

    return OCRResult(words=words)
