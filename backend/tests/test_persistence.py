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
