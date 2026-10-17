"""The server runs in 512 MB, with a JVM beside it during validation.

Measured under that limit with the production image: a 100-page scan was
killed by the kernel mid-validation (exit 137), losing the job. These hold the
pieces that keep it inside the budget.
"""

import fitz

from app.pipeline.orchestrator import _LazyPages
from app.pipeline.validate import jvm_environment


def test_the_jvm_is_lean_even_when_the_host_only_sets_a_heap(monkeypatch):
    """Render's dashboard sets JAVA_TOOL_OPTIONS=-Xmx160m and would override render.yaml."""
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Xmx160m")
    flags = jvm_environment()["JAVA_TOOL_OPTIONS"].split()
    assert "-Xmx160m" in flags
    for f in ("-XX:+UseSerialGC", "-XX:MaxMetaspaceSize=96m", "-XX:ReservedCodeCacheSize=32m",
              "-XX:TieredStopAtLevel=1", "-XX:+ExitOnOutOfMemoryError"):
        assert f in flags, f


def test_a_heap_is_set_when_none_is(monkeypatch):
    monkeypatch.delenv("JAVA_TOOL_OPTIONS", raising=False)
    assert any(f.startswith("-Xmx") for f in jvm_environment()["JAVA_TOOL_OPTIONS"].split())


def test_an_operator_choice_is_not_duplicated(monkeypatch):
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Xmx200m -XX:MaxMetaspaceSize=128m")
    flags = jvm_environment()["JAVA_TOOL_OPTIONS"].split()
    assert flags.count("-Xmx200m") == 1 and not any(f == "-Xmx160m" for f in flags)
    assert sum(1 for f in flags if f.startswith("-XX:MaxMetaspaceSize")) == 1


def test_pages_are_loaded_on_demand_and_numbered_from_one():
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    pages = _LazyPages(doc)
    assert len(pages) == 3
    assert [n for n, _ in pages.items()] == [1, 2, 3]
    assert pages.get(2).number == 1
    assert pages.get(0) is None and pages.get(4) is None
