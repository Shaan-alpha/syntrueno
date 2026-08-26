"""Persistence layer behaviour, and the guarantee that tests stay offline."""

import time

import pytest

from app.config import settings
from app.models import (
    ApprovalRecord,
    AuditLogEntry,
    ExecutionTier,
    RemediationAction,
)
from app.security.human_gate import HumanApprovalGate
from app.storage.audit_ledger import AuditLedger, GENESIS_HASH
from app.storage.firestore_backend import FirestoreBackend
from app.storage.memory_bank import MemoryBank
from app.compiler.recorder import TrajectoryRecorder


def _entry(event_id="evt-1", status="SUCCESS"):
    return AuditLogEntry(
        event_id=event_id, session_id="sess-1", agent_name="SyntruenoCommander",
        action_name="update_cloud_run_resources", status=status,
        details={"memory": "1Gi"}, duration_ms=12.5,
    )


# ============================================================ offline guard

class TestSuiteStaysOffline:
    """A judge must be able to clone and run pytest with no credentials."""

    def test_firestore_is_disabled_during_tests(self):
        assert settings.FIRESTORE_ENABLED is False
        assert FirestoreBackend.available() is False

    def test_gemini_is_disabled_during_tests(self):
        assert settings.SIMULATION_MODE is True

    def test_the_whole_suite_is_fast_enough_to_be_offline(self):
        """A network round trip would blow this budget many times over.

        This exists because enabling Firestore in a local .env silently took
        the suite from 1s to 59s: it was still green, just quietly online.
        """
        start = time.perf_counter()
        for i in range(50):
            AuditLedger.record_entry(_entry(f"evt-{i}"))
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"50 ledger writes took {elapsed:.2f}s; is this hitting the network?"


# =========================================================== audit ledger

class TestAuditLedger:

    def test_a_single_entry_chains_from_genesis(self):
        h = AuditLedger.record_entry(_entry())
        assert len(h) == 64
        entries = AuditLedger.get_all_entries()
        assert entries[0]["prev_hash"] == GENESIS_HASH
        assert AuditLedger.verify_integrity() is True

    def test_each_entry_commits_to_the_one_before_it(self):
        h1 = AuditLedger.record_entry(_entry("evt-1"))
        h2 = AuditLedger.record_entry(_entry("evt-2"))
        h3 = AuditLedger.record_entry(_entry("evt-3"))

        entries = AuditLedger.get_all_entries()
        assert entries[1]["prev_hash"] == h1
        assert entries[2]["prev_hash"] == h2
        assert h1 != h2 != h3
        assert AuditLedger.verify_integrity() is True

    def test_tampering_with_a_past_entry_breaks_the_chain(self):
        AuditLedger.record_entry(_entry("evt-1"))
        AuditLedger.record_entry(_entry("evt-2"))
        AuditLedger.record_entry(_entry("evt-3"))
        assert AuditLedger.verify_integrity() is True

        # Rewrite history: flip a failed action to look successful.
        AuditLedger._memory[0]["status"] = "TAMPERED"
        assert AuditLedger.verify_integrity() is False

    def test_entries_are_sequenced_so_the_head_can_be_recovered(self):
        AuditLedger.record_entry(_entry("evt-1"))
        AuditLedger.record_entry(_entry("evt-2"))
        seqs = [e["sequence"] for e in AuditLedger.get_all_entries()]
        assert seqs == sorted(seqs)
        assert seqs[-1] == 2

    def test_status_reports_whether_it_is_actually_durable(self):
        status = AuditLedger.status()
        assert status["persistent"] is False, "must not claim durability it lacks"

    # ------------------------------------------------ ledger meets the trace

    def test_an_entry_recorded_inside_a_span_carries_that_trace(self, memory_tracer):
        """The ledger says what was decided and that it was not altered. The
        trace says how it was reasoned. Stamping the id is what makes either
        one lead to the other."""
        from app.telemetry.tracing import Tracing

        with Tracing.span("incident"):
            expected_trace, expected_span = Tracing.current_ids()
            AuditLedger.record_entry(_entry("evt-traced"))

        stored = AuditLedger.get_all_entries()[0]
        assert stored["trace_id"] == expected_trace
        assert stored["span_id"] == expected_span

    def test_an_untraced_entry_carries_no_trace_fields_at_all(self):
        """Absent and null are different claims, the same distinction
        FirestoreBackend.query already draws. An entry written with tracing off
        was not sampled; it did not have a null trace."""
        AuditLedger.record_entry(_entry("evt-untraced"))
        stored = AuditLedger.get_all_entries()[0]
        assert "trace_id" not in stored
        assert "span_id" not in stored

    def test_a_chain_mixing_traced_and_untraced_entries_still_validates(
        self, memory_tracer
    ):
        """Adding a field changes what gets hashed, and this ledger's whole
        claim rests on the hash. Entries written before tracing existed must
        keep verifying beside entries written after it -- verified here rather
        than asserted, because a forked chain is silent until someone checks.
        """
        from app.telemetry.tracing import Tracing

        AuditLedger.record_entry(_entry("evt-before"))
        with Tracing.span("incident"):
            AuditLedger.record_entry(_entry("evt-during"))
        AuditLedger.record_entry(_entry("evt-after"))

        entries = AuditLedger.get_all_entries()
        assert [e["sequence"] for e in entries] == [1, 2, 3]
        assert "trace_id" in entries[1]
        assert "trace_id" not in entries[0]
        assert AuditLedger.verify_integrity() is True

    def test_status_reports_the_recovered_head_before_this_container_appends(
        self, monkeypatch
    ):
        """A cold container must not advertise a genesis head over a full ledger.

        Observed live on 2026-08-26: /api/v1/status returned
        ``audit_ledger_size: 26`` beside ``sequence: 0`` and an all-zero
        head_hash. record_entry() recovers the head before appending, so the
        numbers healed on the next write -- but status() read the process-local
        head without recovering it, and status() is what the console polls. The
        one endpoint asserting the ledger is chained was contradicting it.
        """
        head = {"sequence": 26, "chain_hash": "ab" * 32}

        def fake_query(collection, order_by=None, descending=False, limit=None):
            return [head]

        monkeypatch.setattr(FirestoreBackend, "query", staticmethod(fake_query))
        AuditLedger.clear()

        status = AuditLedger.status()
        assert status["sequence"] == 26
        assert status["head_hash"] == "ab" * 32

    def test_a_failed_head_read_does_not_pin_the_container_to_genesis(
        self, monkeypatch
    ):
        """One transient Firestore error must not silently fork the chain.

        _load_head marked itself loaded *before* the query, so a single failed
        read left _latest_hash at genesis for the life of the container. The
        next append then chained from genesis behind a ledger that already had
        entries -- the exact silent fork --max-instances 1 exists to prevent,
        reachable without a second container ever starting.

        query() already distinguishes the two cases: None is "could not read",
        [] is "read fine, nothing there". Only the second is a reason to stop
        asking.
        """
        calls = {"n": 0}
        head = {"sequence": 26, "chain_hash": "cd" * 32}

        def flaky_query(collection, order_by=None, descending=False, limit=None):
            calls["n"] += 1
            return None if calls["n"] == 1 else [head]

        monkeypatch.setattr(FirestoreBackend, "query", staticmethod(flaky_query))
        AuditLedger.clear()

        AuditLedger._load_head()   # transient failure
        AuditLedger._load_head()   # must ask again rather than assume genesis

        assert AuditLedger._sequence == 26
        assert AuditLedger._latest_hash == "cd" * 32

    def test_an_empty_ledger_stops_asking(self, monkeypatch):
        """[] is an answer. Re-reading it on every append would be a round trip
        per write for a ledger that is legitimately empty."""
        calls = {"n": 0}

        def empty_query(collection, order_by=None, descending=False, limit=None):
            calls["n"] += 1
            return []

        monkeypatch.setattr(FirestoreBackend, "query", staticmethod(empty_query))
        AuditLedger.clear()

        AuditLedger._load_head()
        AuditLedger._load_head()

        assert calls["n"] == 1, "an empty read is conclusive; it must not re-query"


# ============================================================= memory bank

class TestMemoryBank:

    def test_a_resolution_is_actually_written(self):
        """The original store had write methods nothing ever called."""
        MemoryBank.record_incident_resolution(
            incident_id="inc-1", service="syntrueno-canary",
            root_cause="OOM at 512Mi", resolution="raise to 1Gi",
            judge_score=8.0, tier="TIER_3_HUMAN_GATE",
        )
        found = MemoryBank.query_similar_incidents("syntrueno-canary")
        assert len(found) == 1
        assert found[0]["root_cause"] == "OOM at 512Mi"

    def test_recall_matches_on_service(self):
        MemoryBank.record_incident_resolution("inc-1", "svc-alpha", "cause A", "fix A")
        MemoryBank.record_incident_resolution("inc-2", "svc-beta", "cause B", "fix B")

        alpha = MemoryBank.query_similar_incidents("svc-alpha")
        assert [i["incident_id"] for i in alpha] == ["inc-1"]

    def test_recall_matches_on_root_cause_text(self):
        MemoryBank.record_incident_resolution("inc-1", "svc-alpha", "connection pool exhausted", "fix")
        found = MemoryBank.query_similar_incidents("connection pool")
        assert found and found[0]["incident_id"] == "inc-1"

    def test_an_empty_bank_recalls_nothing_rather_than_erroring(self):
        assert MemoryBank.query_similar_incidents("anything") == []

    def test_the_commander_records_what_it_learned(self):
        """Guards against the write drifting back out of the request path."""
        import inspect
        from app.agents import commander

        source = inspect.getsource(commander)
        assert "MemoryBank.record_incident_resolution(" in source

    # ------------------------------------------------- two stores, one answer

    def test_recall_reports_when_memory_bank_answered(self, monkeypatch):
        """A memory layer that silently fell back would break the one property
        this project is built on: that it reports what actually happened."""
        from app.memory.vertex_memory import MemoryRecall, VertexMemory

        monkeypatch.setattr(
            VertexMemory, "recall",
            classmethod(lambda cls, scope, query, limit=3: MemoryRecall(
                ok=True,
                memories=[{
                    "fact": "canary OOMKilled at 512Mi",
                    "distance": 0.84,
                    "recorded_at": "2026-08-26T05:27:38Z",
                }],
            )),
        )
        found, source = MemoryBank.recall_for_incident("syntrueno-canary", "oom")

        assert source == "memory_bank"
        assert found[0]["root_cause"] == "canary OOMKilled at 512Mi"
        assert found[0]["distance"] == 0.84

    def test_recall_falls_back_to_firestore_and_says_so(self, monkeypatch):
        from app.memory.vertex_memory import MemoryRecall, VertexMemory

        monkeypatch.setattr(
            VertexMemory, "recall",
            classmethod(lambda cls, scope, query, limit=3: MemoryRecall(
                ok=False, degraded_reason="http_503",
            )),
        )
        MemoryBank.record_incident_resolution(
            incident_id="inc-1", service="syntrueno-canary",
            root_cause="OOM at 512Mi", resolution="raise to 1Gi",
            judge_score=8.0, tier="TIER_3_HUMAN_GATE",
        )
        found, source = MemoryBank.recall_for_incident("syntrueno-canary", "oom")

        assert source == "firestore"
        assert len(found) == 1

    def test_an_empty_memory_bank_result_falls_back_rather_than_recalling_nothing(
        self, monkeypatch
    ):
        """ok with no rows is not an answer worth keeping when Firestore holds
        history. A brand-new memory bank would otherwise erase recall."""
        from app.memory.vertex_memory import MemoryRecall, VertexMemory

        monkeypatch.setattr(
            VertexMemory, "recall",
            classmethod(lambda cls, scope, query, limit=3: MemoryRecall(
                ok=True, memories=[],
            )),
        )
        MemoryBank.record_incident_resolution(
            "inc-1", "syntrueno-canary", "OOM at 512Mi", "raise to 1Gi",
        )
        found, source = MemoryBank.recall_for_incident("syntrueno-canary", "oom")

        assert source == "firestore"
        assert len(found) == 1

    def test_a_resolution_is_written_to_both_stores(self, monkeypatch):
        """Firestore keeps the structured record; Memory Bank keeps the
        searchable copy. Dropping either silently loses a capability."""
        from app.memory.vertex_memory import VertexMemory

        written = {}

        def capture(cls, fact, scope):
            written["fact"] = fact
            written["scope"] = scope
            return True

        monkeypatch.setattr(VertexMemory, "record", classmethod(capture))
        MemoryBank.record_incident_resolution(
            incident_id="inc-1", service="syntrueno-canary",
            root_cause="OOM at 512Mi", resolution="raise to 1Gi",
            judge_score=8.0, tier="TIER_3_HUMAN_GATE",
        )

        assert written["scope"] == {"service_id": "syntrueno-canary"}
        assert "OOM at 512Mi" in written["fact"]
        assert "raise to 1Gi" in written["fact"]


# ================================================================ approvals

class TestApprovalPersistence:

    def test_an_approval_is_retrievable_after_creation(self):
        action = RemediationAction(
            action_id="act-1", tool_name="update_cloud_run_resources",
            parameters={"service_id": "syntrueno-canary", "memory": "1Gi"},
            rationale="raise memory", tier=ExecutionTier.TIER_3_HUMAN_GATE,
        )
        record = HumanApprovalGate.create_pending_approval("inc-1", action)
        fetched = HumanApprovalGate.get(record.approval_id)
        assert fetched is not None
        assert fetched.status == "PENDING"

    def test_approval_ids_are_unpredictable(self):
        """A guessable id would let an attacker sign an approval they never saw."""
        action = RemediationAction(
            action_id="act-1", tool_name="update_cloud_run_resources",
            parameters={"service_id": "syntrueno-canary"},
            rationale="x", tier=ExecutionTier.TIER_3_HUMAN_GATE,
        )
        ids = {
            HumanApprovalGate.create_pending_approval("inc-1", action).approval_id
            for _ in range(20)
        }
        assert len(ids) == 20
        assert all(len(i) > 16 for i in ids)


# ============================================================= trajectories

class TestTrajectoryRecorder:

    def test_an_empty_tool_sequence_is_not_recorded(self):
        """Nothing ran, so there is no trajectory to learn from."""
        TrajectoryRecorder.record_trajectory("metric", [], {}, 0.0)
        assert TrajectoryRecorder.get_all_trajectories() == []

    def test_a_real_sequence_is_recorded_with_its_signature(self):
        TrajectoryRecorder.record_trajectory(
            "container_memory_utilization",
            ["diagnose_incident", "evaluate_action", "create_pending_approval"],
            {"service_id": "syntrueno-canary"}, 1420.5,
        )
        rows = TrajectoryRecorder.get_all_trajectories()
        assert len(rows) == 1
        assert rows[0]["skeleton_signature"] == (
            "diagnose_incident->evaluate_action->create_pending_approval"
        )
        assert rows[0]["duration_ms"] == 1420.5


# ==================================================================
# Concurrent appends must not fork the hash chain.
#
# record_entry is a read-modify-write over _latest_hash and _sequence.
# FastAPI serves sync endpoints from a threadpool, so two incidents
# arriving together share one container and can interleave.
# ==================================================================

def test_concurrent_appends_do_not_fork_the_chain(monkeypatch):
    """The persist call is the yield point that makes the race reachable.

    With set_document returning instantly the GIL hides the interleaving, so
    this test would pass with or without the lock and prove nothing. In
    production that call is a Firestore round trip. Modelling it with a real
    sleep is what makes the read-modify-write actually overlap -- verified by
    removing the lock and watching this fail.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.models import AuditLogEntry
    from app.storage.audit_ledger import AuditLedger
    from app.storage.firestore_backend import FirestoreBackend

    AuditLedger.clear()

    def slow_write(collection, doc_id, record):
        time.sleep(0.002)   # stands in for the network round trip
        return False

    monkeypatch.setattr(FirestoreBackend, "set_document",
                        staticmethod(slow_write))

    def append(i: int) -> str:
        return AuditLedger.record_entry(AuditLogEntry(
            event_id=f"evt-{i:03d}", session_id="sess-concurrent",
            agent_name="sre", action_name="diagnose", status="OK",
            details={"i": i}, duration_ms=1.0,
        ))

    with ThreadPoolExecutor(max_workers=16) as pool:
        hashes = list(pool.map(append, range(40)))

    # Every append produced a distinct link...
    assert len(set(hashes)) == 40
    # ...the chain still validates end to end...
    assert AuditLedger.verify_integrity() is True
    # ...and no two entries claimed the same position.
    sequences = sorted(e["sequence"] for e in AuditLedger._memory)
    assert sequences == list(range(1, 41))


# ==================================================================
# Reported persistence must mean "writes land", not "a client exists".
#
# In production every Firestore call failed with 400 "Invalid database
# id %28default%29" while /api/v1/status reported connected=true,
# last_error=null and persistent=true on every store. The client had
# been constructed successfully and nothing counted what happened next.
# ==================================================================

def test_google_api_core_is_pinned_below_the_broken_release():
    """Guards a silent, total persistence outage.

    google-api-core 2.35.0 encodes the Firestore database id into the
    resource path, so every read and write fails with
    `400 Invalid database id %28default%29` -- while the client still
    constructs, so nothing looks wrong until you read the entries back.
    Bisected 2026-08-25 with google-cloud-firestore and grpcio held constant:
    2.34.0 works, 2.35.0 fails. Loosening the pin brings the outage back.
    """
    from importlib.metadata import version

    installed = tuple(int(p) for p in version("google-api-core").split(".")[:2])
    assert installed < (2, 35), (
        f"google-api-core {version('google-api-core')} breaks Firestore; "
        "see the pin in requirements.txt"
    )


def test_persistence_is_not_claimed_while_every_write_fails(monkeypatch):
    """The exact production condition: client builds, operations all fail."""
    from app.storage.audit_ledger import AuditLedger
    from app.storage.firestore_backend import FirestoreBackend

    FirestoreBackend.reset()

    class Exploding:
        def document(self, _doc_id):
            return self

        def set(self, _data):
            raise RuntimeError("400 Invalid database id %28default%29")

    monkeypatch.setattr(FirestoreBackend, "_init", classmethod(lambda cls: object()))
    monkeypatch.setattr(FirestoreBackend, "collection",
                        classmethod(lambda cls, name: Exploding()))

    assert FirestoreBackend.set_document("audit_ledger", "d1", {"a": 1}) is False

    status = FirestoreBackend.status()
    assert status["operations_failed"] == 1
    assert "Invalid database id" in status["last_operation_error"]
    # The claim that matters, and the one that was wrong in production.
    assert FirestoreBackend.healthy() is False
    assert AuditLedger.status()["persistent"] is False
