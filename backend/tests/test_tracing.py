"""Tracing must be invisible when it fails.

An incident is the product. A trace is a description of the incident. If the
description cannot be written, the incident still has to happen -- so every
path through this module either produces a span or quietly produces nothing,
and none of them raise.
"""

import pytest

from app.config import settings
from app.telemetry.tracing import Tracing


def test_a_disabled_tracer_still_yields_a_usable_span():
    """Callers wrap real work in this. Turning tracing off must not turn the
    work off with it, and must not force every call site into an if."""
    Tracing.reset()
    with Tracing.span("recall", incident_id="inc-1") as span:
        assert span is not None
        result = 2 + 2
    assert result == 4


def test_a_disabled_tracer_reports_no_ids():
    Tracing.reset()
    trace_id, span_id = Tracing.current_ids()
    assert trace_id is None
    assert span_id is None


def test_setting_an_attribute_on_a_noop_span_does_not_raise():
    """The no-op span is handed to code that does not know it is a no-op."""
    Tracing.reset()
    with Tracing.span("diagnose") as span:
        span.set_attribute("judge.score", 8.5)
        span.set_attribute("degraded", False)


def test_a_failing_exporter_degrades_rather_than_raising(monkeypatch):
    """Cloud Trace being unreachable at startup must not stop the service."""
    monkeypatch.setattr(settings, "TRACING_ENABLED", True)
    Tracing.reset()

    def boom(*args, **kwargs):
        raise RuntimeError("no credentials for Cloud Trace")

    monkeypatch.setattr(Tracing, "_build_provider", classmethod(boom))
    Tracing.configure()

    assert Tracing.status()["active"] is False
    assert "RuntimeError" in Tracing.status()["error"]
    # And the span helper still works afterwards.
    with Tracing.span("recall"):
        pass


def test_an_active_tracer_reports_hex_ids_inside_a_span(memory_tracer):
    """The ledger stamps these onto every entry, so they must be the real
    W3C-format ids a trace backend will show, not object reprs."""
    with Tracing.span("recall"):
        trace_id, span_id = Tracing.current_ids()

    assert trace_id and len(trace_id) == 32
    assert span_id and len(span_id) == 16
    int(trace_id, 16)  # raises if not hex
    int(span_id, 16)


def test_an_active_tracer_records_the_span_and_its_attributes(memory_tracer):
    with Tracing.span("judge", model="gemini-3.6-flash", score=8.5):
        pass

    spans = memory_tracer.get_finished_spans()
    assert [s.name for s in spans] == ["judge"]
    assert spans[0].attributes["model"] == "gemini-3.6-flash"
    assert spans[0].attributes["score"] == 8.5


def test_none_attributes_are_dropped_rather_than_sent(memory_tracer):
    """OTel rejects None attribute values. Half this codebase's telemetry is
    optional -- degraded_reason, latency on a failed call -- so passing them
    through unfiltered would raise inside the tracer, from the one module that
    must never raise."""
    with Tracing.span("diagnose", model="x", degraded_reason=None):
        pass

    attributes = memory_tracer.get_finished_spans()[0].attributes
    assert "degraded_reason" not in attributes
    assert attributes["model"] == "x"


def test_nested_spans_share_one_trace(memory_tracer):
    """A judge following an audit entry back to its reasoning needs the whole
    incident under one trace, not five unrelated ones."""
    with Tracing.span("incident"):
        outer_trace, _ = Tracing.current_ids()
        with Tracing.span("diagnose"):
            inner_trace, _ = Tracing.current_ids()

    assert outer_trace == inner_trace
    assert {s.name for s in memory_tracer.get_finished_spans()} == {
        "incident", "diagnose",
    }
