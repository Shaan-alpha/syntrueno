"""Swarm coordinator.

Dispatches to the specialist agents over an enforced zero-trust boundary. Every
dispatch mints a scoped, short-lived A2A capability token and verifies it before
the receiving agent does any work.

The coordinator is written as a **generator of stage events**. A real incident
takes 15-25 seconds of model time, and a console that shows nothing during that
window has to invent progress to stay interesting. Yielding each stage as it
actually completes lets the UI report real durations and real model names rather
than a choreographed animation. ``process_incident`` simply drains the
generator, so the streaming and blocking paths can never drift apart.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List

from app.agents.judge import JudgeAgent
from app.agents.sre import SREAgent
from app.models import (
    AuditLogEntry,
    ExecutionTier,
    IncidentAlert,
    RemediationTool,
)
from app.security.human_gate import HumanApprovalGate
from app.security.token_auth import A2ATokenAuthority
from app.storage.audit_ledger import AuditLedger
from app.storage.memory_bank import MemoryBank

# The stages a console can expect, in order. Declared so the UI can render the
# whole track upfront and fill it in, instead of growing it as events arrive.
STAGES: List[str] = ["recall", "diagnose", "judge", "gate", "record"]


def _event(stage: str, state: str, **extra: Any) -> Dict[str, Any]:
    return {"type": "stage", "stage": stage, "state": state, **extra}


class SyntruenoCommander:
    """Coordinates incident response across the specialist agents."""

    NAME = "SyntruenoCommander"

    # ------------------------------------------------------------ streaming

    @classmethod
    def run(
        cls, alert: IncidentAlert, user_session: str = "sess-default"
    ) -> Iterator[Dict[str, Any]]:
        """Yield stage events as the swarm works, then a final result event."""
        started = time.perf_counter()
        executed_tools: List[str] = []
        degraded_reasons: List[str] = []

        yield {"type": "start", "incident_id": alert.incident_id, "stages": STAGES}

        # 1 - Recall prior incidents on this service.
        yield _event("recall", "active")
        t0 = time.perf_counter()
        # The alert text, not just the service name: Memory Bank matches on
        # meaning, so the wording of what went wrong is the useful query.
        past_incidents, memory_source = MemoryBank.recall_for_incident(
            alert.service_id, alert.error_message, limit=2
        )
        executed_tools.append("recall_incident_history")
        yield _event(
            "recall", "done",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            detail=(
                f"{len(past_incidents)} prior incident(s) on this service "
                f"via {memory_source}"
            ),
        )

        # 2 - Diagnose, under a token scoped to diagnosis only.
        yield _event("diagnose", "active")
        sre_token = A2ATokenAuthority.mint_token(
            source_agent=cls.NAME, target_agent="SREAgent",
            capability="diagnose_incident",
        )
        A2ATokenAuthority.require(sre_token, "SREAgent", "diagnose_incident")
        sre_result = SREAgent.diagnose_and_plan(alert)
        executed_tools.append("diagnose_incident")
        if sre_result.get("degraded"):
            degraded_reasons.append(f"sre:{sre_result.get('degraded_reason')}")

        action = sre_result["remediation_action"]
        sre_tel = sre_result.get("telemetry", {})
        yield _event(
            "diagnose", "degraded" if sre_result.get("degraded") else "done",
            duration_ms=sre_tel.get("latency_ms"),
            model=sre_tel.get("model"),
            tokens=sre_tel.get("total_tokens"),
            detail=sre_result["root_cause"],
            confidence=sre_result.get("confidence"),
            tool=action.tool_name,
            degraded_reason=sre_result.get("degraded_reason"),
        )

        # 3 - Judge, under its own token. A diagnosis token cannot be replayed
        #     here to obtain a safety evaluation.
        yield _event("judge", "active")
        judge_token = A2ATokenAuthority.mint_token(
            source_agent=cls.NAME, target_agent="AuditorAgent",
            capability="evaluate_action",
        )
        A2ATokenAuthority.require(judge_token, "AuditorAgent", "evaluate_action")
        evaluation = JudgeAgent.evaluate_action(
            incident_context=(
                f"{alert.severity.value} on {alert.service_id}. "
                f"metric={alert.metric_name}. {alert.error_message[:300]}"
            ),
            action=action,
        )
        executed_tools.append("evaluate_action")
        if evaluation.degraded:
            degraded_reasons.append(f"judge:{evaluation.degraded_reason}")

        yield _event(
            "judge", "degraded" if evaluation.degraded else "done",
            duration_ms=evaluation.telemetry.get("latency_ms"),
            model=evaluation.telemetry.get("model"),
            tokens=evaluation.telemetry.get("total_tokens"),
            score=evaluation.score,
            approved=evaluation.is_approved,
            detail=evaluation.critique,
            degraded_reason=evaluation.degraded_reason,
        )

        # 4 - Resolve the tier and gate on it.
        yield _event("gate", "active")
        resolved_tier = JudgeAgent.resolve_tier(evaluation)
        action.tier = resolved_tier

        approval_record = None
        if action.tool_name == RemediationTool.NO_ACTION.value:
            execution_status = "NO_ACTION_REQUIRED"
        elif resolved_tier == ExecutionTier.TIER_3_HUMAN_GATE:
            approval_record = HumanApprovalGate.create_pending_approval(
                alert.incident_id, action
            )
            execution_status = "AWAITING_HUMAN_SIGNATURE"
            executed_tools.append("create_pending_approval")
        else:
            # Clearance to attempt, not to succeed: the mutation still passes
            # every guard in CloudRunAdmin.
            execution_status = "CLEARED_FOR_AUTONOMOUS_EXECUTION"

        yield _event(
            "gate", "done",
            tier=resolved_tier.value,
            status=execution_status,
            approval_id=approval_record.approval_id if approval_record else None,
            detail=(
                "Signed human approval required before execution."
                if approval_record
                else "No human signature required at this tier."
            ),
        )

        # 5 - Persist what we learned and seal the audit entry.
        yield _event("record", "active")
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        MemoryBank.record_incident_resolution(
            incident_id=alert.incident_id,
            service=alert.service_id,
            root_cause=sre_result["root_cause"],
            resolution=action.rationale,
            judge_score=evaluation.score,
            tier=resolved_tier.value,
        )
        executed_tools.append("record_incident_resolution")

        ledger_hash = AuditLedger.record_entry(
            AuditLogEntry(
                event_id=f"evt-{alert.incident_id[-4:]}-{int(time.time() * 1000) % 100000}",
                session_id=user_session,
                agent_name=cls.NAME,
                action_name=action.tool_name,
                status=execution_status,
                details={
                    "incident_id": alert.incident_id,
                    "judge_score": evaluation.score,
                    "tier": resolved_tier.value,
                    "degraded": bool(degraded_reasons),
                },
                duration_ms=duration_ms,
            )
        )
        yield _event(
            "record", "done",
            detail="Sealed into the audit chain",
            chain_hash=ledger_hash,
        )

        yield {
            "type": "result",
            "result": {
                "incident_id": alert.incident_id,
                "execution_status": execution_status,
                "sre_diagnosis": sre_result["root_cause"],
                "sre_confidence": sre_result.get("confidence"),
                "proposed_action": action.model_dump(),
                "judge_evaluation": evaluation.model_dump(),
                "resolved_tier": resolved_tier.value,
                "approval_record": approval_record.model_dump() if approval_record else None,
                "past_memory_context": past_incidents,
                # Named rather than implied. A silent fallback to Firestore
                # looks identical to a working semantic recall from the
                # outside, and that is exactly the kind of invisible
                # degradation this system exists to refuse.
                "past_memory_source": memory_source,
                "ledger_chain_hash": ledger_hash,
                "executed_tools": executed_tools,
                "degraded": bool(degraded_reasons),
                "degraded_reasons": degraded_reasons,
                "telemetry": {
                    "sre": sre_tel,
                    "judge": evaluation.telemetry,
                    "total_duration_ms": duration_ms,
                },
                "total_duration_ms": duration_ms,
            },
        }

    # ------------------------------------------------------------- blocking

    @classmethod
    def process_incident(
        cls, alert: IncidentAlert, user_session: str = "sess-default"
    ) -> Dict[str, Any]:
        """Run to completion and return the final result."""
        final: Dict[str, Any] = {}
        for event in cls.run(alert, user_session):
            if event.get("type") == "result":
                final = event["result"]
        return final
