from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    ran: bool
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def epubcheck_available() -> bool:
    return shutil.which(settings.epubcheck_binary) is not None


def validate_epub(epub_path: Path) -> ValidationResult:
    """Run EPUBCheck and require a real pass before a conversion is marked
    successful (spec section 37) — never present a critically invalid EPUB."""
    if not epubcheck_available():
        logger.warning("epubcheck binary not found on PATH; skipping validation")
        return ValidationResult(ran=False, passed=False, errors=["epubcheck is not installed on this server"])

    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.json"
        try:
            subprocess.run(
                [settings.epubcheck_binary, str(epub_path), "--json", str(report_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(ran=True, passed=False, errors=["EPUBCheck timed out"])

        if not report_path.exists():
            return ValidationResult(ran=True, passed=False, errors=["EPUBCheck produced no report"])

        report = json.loads(report_path.read_text())

    messages = report.get("messages", [])
    errors = [
        f'{m.get("ID", "")}: {m.get("message", "")}'
        for m in messages
        if m.get("severity") in ("ERROR", "FATAL")
    ]
    warnings = [f'{m.get("ID", "")}: {m.get("message", "")}' for m in messages if m.get("severity") == "WARNING"]

    return ValidationResult(ran=True, passed=len(errors) == 0, errors=errors, warnings=warnings)
