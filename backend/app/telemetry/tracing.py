"""OpenTelemetry tracing for the swarm, exported to Cloud Trace.

Track 3 asks for audit logs *and* reasoning-chain traces. The hash-chained
ledger in app/storage/audit_ledger.py is the first half and was already here;
this is the second. They are deliberately joined rather than parallel: every
ledger entry carries the trace_id and span_id of the reasoning that produced it,
so the ledger says what was decided and that it was not altered, while the trace
says how it was reasoned, and either one leads to the other.

Same hard contract as every other external dependency in this codebase: **it
never raises to its callers.** An incident is the product and a trace is a
description of the incident; if the description cannot be written the incident
still has to happen. So ``span()`` yields a working no-op when tracing is off or
broken, and callers never need to ask which.

Export runs through a BatchSpanProcessor on a background thread. Exporting
inline would put Cloud Trace's latency inside every stage, which is exactly the
kind of number this project refuses to quietly inflate.

That alone is not enough on Cloud Run. CPU is throttled between requests, so the
background thread gets no time once a response is sent and the queued spans are
never exported at all. The first deploy of this module reported tracing active
while the project held zero traces -- the same shape of lie FirestoreBackend was
built to stop telling. ``flush()`` closes it by pushing spans out at the end of
the request, while it still holds CPU, and ``status()`` counts what actually
left rather than what was queued.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

SERVICE_NAME = "syntrueno"


class _NoopSpan:
    """Stands in for a span when tracing is off or failed to start.

    Callers hand this real telemetry without knowing it is a no-op, so it has to
    absorb every method they would use on a live span.
    """

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def set_attributes(self, attributes: Dict[str, Any]) -> None:
        return None

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        return None

    def record_exception(self, exception: BaseException) -> None:
        return None

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        return None


_NOOP = _NoopSpan()


class Tracing:
    """Tracer lifecycle and span helper."""

    _tracer: Any = None
    _provider: Any = None
    _configured: bool = False
    _error: Optional[str] = None

    # Counting what actually left, not what was queued. status() reporting
    # active=true while the project held zero traces is the same failure
    # FirestoreBackend documents: a constructed client proves nothing about
    # whether operations land.
    _flushes_ok: int = 0
    _flushes_failed: int = 0
    _last_flush_error: Optional[str] = None

    @classmethod
    def reset(cls) -> None:
        """Test helper, and the hook conftest uses to keep the suite offline."""
        cls._tracer = None
        cls._provider = None
        cls._configured = False
        cls._error = None
        cls._flushes_ok = 0
        cls._flushes_failed = 0
        cls._last_flush_error = None

    # --------------------------------------------------------------- startup

    @classmethod
    def _build_provider(cls) -> Any:
        """The real Cloud Trace provider.

        Separated so tests can substitute an in-memory exporter without a
        test-only entry point on this class, and so the failure path below is
        the same code in both cases.
        """
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME as RESOURCE_SERVICE_NAME
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({RESOURCE_SERVICE_NAME: SERVICE_NAME})
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                CloudTraceSpanExporter(project_id=settings.GOOGLE_CLOUD_PROJECT)
            )
        )
        return provider

    @classmethod
    def configure(cls) -> None:
        """Start tracing. Safe to call more than once, and safe to fail."""
        if cls._configured:
            return
        cls._configured = True

        if not settings.TRACING_ENABLED:
            return

        try:
            from opentelemetry import trace

            provider = cls._build_provider()
            trace.set_tracer_provider(provider)
            cls._provider = provider
            cls._tracer = provider.get_tracer(SERVICE_NAME)
            logger.info("Tracing active, exporting to Cloud Trace")
        except Exception as exc:
            # Missing credentials, a disabled API, an import failure -- none of
            # them are reasons to refuse to serve incidents.
            cls._error = f"{type(exc).__name__}: {str(exc)[:160]}"
            cls._tracer = None
            logger.warning("Tracing unavailable, continuing without it: %s", cls._error)

    @classmethod
    def active(cls) -> bool:
        return cls._tracer is not None

    # ----------------------------------------------------------------- spans

    @staticmethod
    def _clean(attributes: Dict[str, Any]) -> Dict[str, Any]:
        """Drop None values.

        OTel rejects a None attribute value, and much of this codebase's
        telemetry is legitimately optional -- degraded_reason on a call that did
        not degrade, latency on one that never returned. Passing those through
        would raise from inside the one module that must not raise.
        """
        return {k: v for k, v in attributes.items() if v is not None}

    @classmethod
    @contextmanager
    def span(cls, name: str, **attributes: Any) -> Iterator[Any]:
        """Run a block inside a span, or transparently without one."""
        cls.configure()
        if cls._tracer is None:
            yield _NOOP
            return

        try:
            with cls._tracer.start_as_current_span(name) as span:
                span.set_attributes(cls._clean(attributes))
                yield span
        except Exception as exc:
            # A tracer that breaks mid-incident must not take the incident with
            # it. The work inside the block has already run or raised on its
            # own; this only swallows failures of the tracing itself.
            logger.warning("Span %r failed, continuing untraced: %s", name, exc)
            yield _NOOP

    @staticmethod
    def annotate(span: Any, **attributes: Any) -> None:
        """Set attributes that only exist once the work is done.

        A judge score and a resolved tier do not exist when the incident span
        opens, but they belong on that span rather than only on a child. Safe on
        a no-op span, and drops None for the same reason ``span()`` does.
        """
        try:
            span.set_attributes(Tracing._clean(attributes))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Span annotation failed, continuing: %s", exc)

    @classmethod
    def current_ids(cls) -> Tuple[Optional[str], Optional[str]]:
        """The active trace and span ids, W3C hex, or ``(None, None)``.

        These are what the audit ledger stamps onto each entry, so they have to
        be the ids a trace backend will actually show.
        """
        if cls._tracer is None:
            return (None, None)
        try:
            from opentelemetry import trace

            context = trace.get_current_span().get_span_context()
            if not context.is_valid:
                return (None, None)
            return (format(context.trace_id, "032x"), format(context.span_id, "016x"))
        except Exception:
            return (None, None)

    @classmethod
    def flush(cls, timeout_millis: int = 2000) -> bool:
        """Push pending spans out before the request ends.

        Cloud Run throttles CPU between requests. BatchSpanProcessor exports on
        a background thread, and that thread gets no CPU once the response has
        been sent -- so without this the spans are queued, never exported, and
        the service reports tracing as active while the project holds zero
        traces. Observed exactly that way on 2026-08-26.

        The cost is real and deliberate: this blocks the request for up to
        ``timeout_millis``. The alternative is a SimpleSpanProcessor exporting
        inline on every span, which would put Cloud Trace latency inside each
        stage rather than once at the end.
        """
        if cls._provider is None:
            return False
        try:
            cls._provider.force_flush(timeout_millis)
            cls._flushes_ok += 1
            cls._last_flush_error = None
            return True
        except Exception as exc:
            cls._flushes_failed += 1
            cls._last_flush_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Trace flush failed: %s", cls._last_flush_error)
            return False

    @classmethod
    def status(cls) -> Dict[str, Any]:
        """What this layer is, for /api/v1/status."""
        return {
            "enabled": settings.TRACING_ENABLED,
            # Configured is not the same as working, the same distinction
            # FirestoreBackend draws between a built client and landed writes.
            "active": cls.active(),
            "exporter": "cloud_trace",
            "error": cls._error,
            # And these are the ones to read: spans queued is not spans exported.
            "flushes_ok": cls._flushes_ok,
            "flushes_failed": cls._flushes_failed,
            "last_flush_error": cls._last_flush_error,
        }
