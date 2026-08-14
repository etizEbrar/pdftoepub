"""The cost guarantee, enforced mechanically.

Every advanced feature — OCR, tables, formulas, endnotes, poetry, RTL — must
work with `AI_PROVIDER=none` and no API key, and the pipeline must never open a
network connection to a paid provider. These tests fail loudly if that ever
stops being true.
"""

from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest

from app.core.config import settings
from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.ai.provider import get_provider
from app.pipeline.orchestrator import _run_pipeline_sync
from app.pipeline.validate import epubcheck_available
from tests.fixtures.corpus import (
    build_endnote_document,
    build_formula_document,
    build_poetry_document,
    build_rtl_document,
    build_scanned_book,
    build_table_document,
)

requires_epubcheck = pytest.mark.skipif(
    not epubcheck_available(), reason="epubcheck is not installed"
)


class NetworkBlockedError(AssertionError):
    """Raised when the pipeline attempts any outbound network connection."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Make every outbound socket connection fail loudly.

    Local processing must not need the network at all, so any attempt is a
    defect — whether it is a paid AI provider or something else phoning home.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def blocked(self, address, *args, **kwargs):  # noqa: ANN001
        raise NetworkBlockedError(f"pipeline attempted a network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: blocked(None, a[0] if a else None))
    yield
    monkeypatch.setattr(socket.socket, "connect", real_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", real_connect_ex)


def _run(job_id: str, pdf: Path) -> Job:
    job = Job(
        job_id=job_id,
        source_filename=pdf.name,
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(pdf),
    )
    store.save_job(job)
    try:
        _run_pipeline_sync(job)
    finally:
        store.delete_job(job_id)
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)
    return job


def test_default_configuration_requires_no_api_key():
    assert settings.ai_provider == "none"
    provider = get_provider(settings.ai_provider, anthropic_api_key=settings.anthropic_api_key)
    assert provider.name == "none"
    assert provider.requires_network is False


def test_selecting_a_cloud_provider_without_a_key_falls_back_to_local_not_failure():
    provider = get_provider("anthropic", anthropic_api_key=None)
    assert provider.name == "local"
    assert provider.requires_network is False


def test_local_provider_never_requires_network():
    assert get_provider("local").requires_network is False


@requires_epubcheck
@pytest.mark.parametrize(
    "name,builder",
    [
        ("scanned", build_scanned_book),
        ("tables", build_table_document),
        ("formulas", build_formula_document),
        ("endnotes", build_endnote_document),
        ("poetry", build_poetry_document),
        ("rtl", build_rtl_document),
    ],
)
def test_every_advanced_feature_converts_with_no_network_and_no_api_key(
    tmp_path: Path, no_network, name: str, builder
):
    """OCR, tables, formulas, endnotes, poetry and RTL each convert to a valid
    EPUB with the network hard-blocked and AI_PROVIDER=none."""
    assert settings.ai_provider == "none"
    pdf = builder(tmp_path / f"{name}.pdf")

    job = _run(f"nopaid-{name}", pdf)

    assert job.stage == JobStage.COMPLETED, f"{name}: {job.error_code} {job.error_message}"
    assert job.quality_report is not None
    assert job.quality_report.ai_provider_used == "none"
    assert job.quality_report.ai_blocks_reviewed >= 0
    assert job.quality_report.epubcheck_passed is True


def test_anthropic_provider_is_never_constructed_without_an_explicit_key(monkeypatch):
    """Guards against a refactor that quietly makes the cloud path the default."""
    constructed = {"count": 0}

    class Boom:
        def __init__(self, *args, **kwargs):
            constructed["count"] += 1

    monkeypatch.setattr("app.pipeline.ai.anthropic_provider.AnthropicProvider", Boom)

    get_provider("none")
    get_provider("local")
    get_provider("anthropic", anthropic_api_key=None)
    get_provider("openai")
    get_provider("google")

    assert constructed["count"] == 0
