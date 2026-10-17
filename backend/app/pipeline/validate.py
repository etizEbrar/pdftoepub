from __future__ import annotations

import json
import shutil
import os
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


# A JVM's footprint is its heap plus metaspace, code cache, thread stacks and
# compiler threads. Measured: with only -Xmx160m EPUBCheck peaked at 236 MB;
# with these as well, 154 MB for the same book and the same heap. Applied here
# rather than only in render.yaml, because a value set in the hosting dashboard
# would otherwise override the file and quietly bring the 236 MB back.
_LEAN_JVM_FLAGS = (
    "-XX:+UseSerialGC",
    "-Xss512k",
    "-XX:MaxMetaspaceSize=96m",
    "-XX:ReservedCodeCacheSize=32m",
    "-XX:TieredStopAtLevel=1",
    "-XX:CICompilerCount=1",
    "-XX:+ExitOnOutOfMemoryError",
)
_DEFAULT_HEAP = "-Xmx160m"


def jvm_environment() -> dict[str, str]:
    """The environment EPUBCheck runs in: the caller's, plus a lean JVM."""
    env = dict(os.environ)
    current = env.get("JAVA_TOOL_OPTIONS", "").split()
    flags = list(current)
    if not any(f.startswith("-Xmx") for f in flags):
        flags.append(_DEFAULT_HEAP)
    for flag in _LEAN_JVM_FLAGS:
        name = flag.split("=")[0].lstrip("-").lstrip("X:").lstrip("+-")
        if not any(name in f for f in current):
            flags.append(flag)
    env["JAVA_TOOL_OPTIONS"] = " ".join(flags)
    return env


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
                env=jvm_environment(),
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
