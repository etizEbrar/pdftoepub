"""Production hardening of the public API surface.

These are the checks that matter once the backend is reachable from the
internet rather than from a laptop on the same desk.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, apply_environment_defaults


@pytest.fixture
def client(monkeypatch):
    import app.main

    c = TestClient(app.main.app, raise_server_exceptions=False)
    # Each test starts with a clean throttle so ordering can't cause failures.
    app.main._request_limiter.reset()
    import app.api.routes

    app.api.routes._upload_limiter.reset()
    yield c
    app.main._request_limiter.reset()
    app.api.routes._upload_limiter.reset()


def _pdf_bytes(size: int = 2048) -> bytes:
    return b"%PDF-1.4\n" + b"0" * size


class TestUploadValidation:
    def test_non_pdf_content_is_rejected_by_magic_bytes(self, client):
        r = client.post(
            "/v1/conversions",
            files={"file": ("book.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        )
        assert r.status_code == 400
        assert r.json()["code"] == "unsupported_pdf"

    def test_non_pdf_extension_is_rejected(self, client):
        r = client.post(
            "/v1/conversions",
            files={"file": ("payload.exe", _pdf_bytes(), "application/pdf")},
        )
        assert r.status_code == 400

    def test_empty_upload_is_rejected(self, client):
        r = client.post("/v1/conversions", files={"file": ("book.pdf", b"", "application/pdf")})
        assert r.status_code == 400

    def test_oversized_upload_is_refused_and_leaves_nothing_behind(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_upload_mb", 1)
        before = set(settings.jobs_dir.iterdir()) if settings.jobs_dir.exists() else set()

        r = client.post(
            "/v1/conversions",
            files={"file": ("big.pdf", _pdf_bytes(3 * 1024 * 1024), "application/pdf")},
        )
        assert r.status_code == 400
        assert r.json()["code"] == "file_too_large"

        after = set(settings.jobs_dir.iterdir()) if settings.jobs_dir.exists() else set()
        assert after == before, "a rejected upload must not leave a partial file on disk"


class TestJobIDHandling:
    @pytest.mark.parametrize(
        "job_id",
        [
            "../../../etc/passwd",
            "..",
            "%2e%2e%2f%2e%2e",
            "'; DROP TABLE jobs;--",
            "x" * 500,
            "NOTHEX" * 5,
        ],
    )
    def test_hostile_job_ids_are_refused_without_touching_the_filesystem(self, client, job_id):
        for suffix in ("", "/progress", "/result", "/download"):
            r = client.get(f"/v1/conversions/{job_id}{suffix}")
            assert r.status_code in (404, 405), f"{job_id}{suffix} returned {r.status_code}"

    def test_deleting_a_hostile_job_id_does_not_remove_the_jobs_directory(self, client):
        from app.core.config import settings

        settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        r = client.delete("/v1/conversions/..")
        assert r.status_code == 404
        assert settings.jobs_dir.exists(), "the jobs directory must still be there"

    def test_generated_job_ids_are_random_hex(self, client):
        r = client.post(
            "/v1/conversions", files={"file": ("b.pdf", _pdf_bytes(), "application/pdf")}
        )
        assert r.status_code == 201
        job_id = r.json()["id"]
        assert len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id)


class TestErrorResponses:
    def test_unknown_job_reveals_no_server_path(self, client):
        r = client.get("/v1/conversions/" + "0" * 32 + "/download")
        assert r.status_code == 404
        body = r.text
        for leak in ("/Users/", "/home/", "Traceback", "site-packages", ".py"):
            assert leak not in body

    def test_error_bodies_never_carry_a_traceback(self, client):
        r = client.post(
            "/v1/conversions", files={"file": ("b.pdf", b"garbage", "application/pdf")}
        )
        assert "Traceback" not in r.text
        assert "File \"" not in r.text


class TestDownloadFilename:
    def test_header_injection_via_filename_is_neutralised(self):
        from app.api.routes import _safe_download_name

        nasty = 'evil"; filename="owned.exe\r\nX-Injected: yes\r\n\r\n.pdf'
        safe = _safe_download_name(nasty)
        for ch in ('"', "\r", "\n", ";"):
            assert ch not in safe
        assert safe.endswith(".epub")

    def test_a_normal_name_survives_readably(self):
        from app.api.routes import _safe_download_name

        assert _safe_download_name("My Book.pdf") == "My Book.epub"

    def test_a_name_of_only_unsafe_characters_still_yields_a_filename(self):
        from app.api.routes import _safe_download_name

        assert _safe_download_name("\r\n\"';.pdf").endswith(".epub")


class TestHealthEndpoint:
    def test_health_is_minimal_and_leaks_nothing(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"status", "ai_provider"}, f"unexpected keys: {set(body)}"
        assert body["status"] == "ok"
        # No paths, secrets, versions or environment details.
        text = r.text
        for leak in ("/Users/", "/home/", "data_dir", "api_key", "secret", "password"):
            assert leak not in text

    def test_health_reports_that_no_paid_ai_is_in_use(self, client):
        assert client.get("/health").json()["ai_provider"] == "none"


class TestRateLimiting:
    def test_repeated_uploads_are_eventually_throttled(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "rate_limit_uploads_per_hour", 3)
        import app.api.routes as routes
        from app.api.ratelimit import SlidingWindowLimiter

        monkeypatch.setattr(routes, "_upload_limiter", SlidingWindowLimiter(3, 3600.0))

        codes = [
            client.post(
                "/v1/conversions", files={"file": ("b.pdf", _pdf_bytes(), "application/pdf")}
            ).status_code
            for _ in range(5)
        ]
        assert 429 in codes, f"expected throttling, got {codes}"

    def test_a_throttled_response_says_when_to_retry(self, client, monkeypatch):
        import app.api.routes as routes
        from app.api.ratelimit import SlidingWindowLimiter

        monkeypatch.setattr(routes, "_upload_limiter", SlidingWindowLimiter(1, 3600.0))
        client.post("/v1/conversions", files={"file": ("b.pdf", _pdf_bytes(), "application/pdf")})
        r = client.post(
            "/v1/conversions", files={"file": ("b.pdf", _pdf_bytes(), "application/pdf")}
        )
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) > 0

    def test_a_rejected_upload_does_not_consume_quota(self, client, monkeypatch):
        """A user fumbling with the wrong file shouldn't lock themselves out."""
        import app.api.routes as routes
        from app.api.ratelimit import SlidingWindowLimiter

        monkeypatch.setattr(routes, "_upload_limiter", SlidingWindowLimiter(2, 3600.0))
        for _ in range(5):
            client.post(
                "/v1/conversions", files={"file": ("x.txt", b"nope", "application/pdf")}
            )
        r = client.post(
            "/v1/conversions", files={"file": ("b.pdf", _pdf_bytes(), "application/pdf")}
        )
        assert r.status_code == 201, "valid upload blocked by quota spent on rejected ones"

    def test_health_is_never_throttled(self, client, monkeypatch):
        """The platform's health probe must not be able to lock itself out."""
        import app.main
        from app.api.ratelimit import SlidingWindowLimiter

        monkeypatch.setattr(app.main, "_request_limiter", SlidingWindowLimiter(1, 60.0))
        assert all(client.get("/health").status_code == 200 for _ in range(5))


class TestSecurityHeaders:
    def test_responses_carry_hardening_headers(self, client):
        r = client.get("/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


class TestProductionDefaults:
    def test_production_hides_the_interactive_docs(self, monkeypatch):
        monkeypatch.delenv("EXPOSE_API_DOCS", raising=False)
        s = apply_environment_defaults(Settings(environment="production"))
        assert s.expose_api_docs is False
        assert s.is_production

    def test_development_keeps_the_docs(self, monkeypatch):
        monkeypatch.delenv("EXPOSE_API_DOCS", raising=False)
        s = apply_environment_defaults(Settings(environment="development"))
        assert s.expose_api_docs is True

    def test_production_binds_all_interfaces_so_health_checks_reach_it(self, monkeypatch):
        monkeypatch.delenv("HOST", raising=False)
        s = apply_environment_defaults(Settings(environment="production"))
        assert s.host == "0.0.0.0"

    def test_ai_stays_off_by_default_in_every_environment(self):
        for env in ("development", "staging", "production"):
            assert apply_environment_defaults(Settings(environment=env)).ai_provider == "none"

    def test_cors_is_closed_unless_configured(self):
        assert Settings().cors_origins == []
        assert Settings(cors_allow_origins="https://a.example, https://b.example").cors_origins == [
            "https://a.example",
            "https://b.example",
        ]


class TestLimits:
    def test_a_page_count_ceiling_is_configured(self):
        from app.core.config import settings

        assert settings.max_page_count > 0

    def test_a_conversion_timeout_is_configured(self):
        from app.core.config import settings

        assert settings.conversion_timeout_seconds > 0


class TestRetention:
    """Nothing about a converted book may outlive its TTL."""

    def test_the_sweep_removes_both_the_files_and_the_database_row(self, tmp_path, monkeypatch):
        import os
        import time
        from datetime import datetime, timedelta

        from app.core.config import settings
        from app.jobs import store
        from app.models.job import ConversionMode, Job
        from app.storage.temp_storage import job_dir, sweep_expired_jobs

        monkeypatch.setattr(settings, "data_dir", tmp_path)
        (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)

        job_id = "a" * 32
        d = job_dir(job_id)
        (d / "source").mkdir(parents=True, exist_ok=True)
        (d / "source" / "Private Diary.pdf").write_bytes(b"%PDF-1.4 secret")

        job = Job(
            job_id=job_id,
            source_filename="Private Diary.pdf",
            mode=ConversionMode.MAXIMUM_ACCURACY,
            upload_path=str(d / "source" / "Private Diary.pdf"),
        )
        job.updated_at = datetime.now() - timedelta(hours=48)
        store.save_job(job)
        assert store.get_job(job_id) is not None

        # The directory sweep goes by mtime, so age the directory as well as the
        # row — otherwise this would only ever exercise half the sweep.
        old = time.time() - 48 * 3600
        os.utime(d, (old, old))

        sweep_expired_jobs(ttl_hours=1)

        assert not d.exists(), "the uploaded document must be gone"
        assert store.get_job(job_id) is None, (
            "the database row still names the user's file after the TTL expired"
        )

    def test_the_sweep_leaves_a_fresh_job_alone(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.jobs import store
        from app.models.job import ConversionMode, Job
        from app.storage.temp_storage import job_dir, sweep_expired_jobs

        monkeypatch.setattr(settings, "data_dir", tmp_path)
        (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)

        job_id = "b" * 32
        job_dir(job_id)
        store.save_job(
            Job(
                job_id=job_id,
                source_filename="current.pdf",
                mode=ConversionMode.MAXIMUM_ACCURACY,
                upload_path=str(job_dir(job_id) / "source" / "current.pdf"),
            )
        )
        sweep_expired_jobs(ttl_hours=24)
        assert store.get_job(job_id) is not None, "an in-flight job must not be swept"
