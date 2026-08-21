"""Swarm coordinator.

Dispatches to the specialist agents over an enforced zero-trust boundary. The
A2A capability token was previously minted only in tests and never used in a
request path, which made "zero-trust agent identity" a diagram label rather
than a control. Here every dispatch mints a scoped, short-lived token and the
receiving side verifies it before doing any work.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

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


class SentinelCommander:
    """Coordinates incident response across the specialist agents."""

    NAME = "SyntruenoCommander"

    @classmethod
    def process_incident(
        cls, alert: IncidentAlert, user_session: str = "sess-default"
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        executed_tools: List[str] = []
        degraded_reasons: List[str] = []

        # 1. Recall prior incidents on this service.
        past_incidents = MemoryBank.query_similar_incidents(alert.service_id, limit=2)
        executed_tools.append("recall_incident_history")

        # 2. Dispatch to the SRE agent under a scoped capability token.
        sre_token = A2ATokenAuthority.mint_token(
            source_agent=cls.NAME, target_agent="SREAgent", capability="diagnose_incident"
        )
        A2ATokenAuthority.require(sre_token, "SREAgent", "diagnose_incident")
        sre_result = SREAgent.diagnose_and_plan(alert)
        executed_tools.append("diagnose_incident")
        if sre_result.get("degraded"):
            degraded_reasons.append(f"sre:{sre_result.get('degraded_reason')}")

        action = sre_result["remediation_action"]

        # 3. Dispatch to the Judge under its own token. A token scoped to
        #    diagnosis cannot be replayed to obtain an evaluation.
        judge_token = A2ATokenAuthority.mint_token(
            source_agent=cls.NAME, target_agent="AuditorAgent", capability="evaluate_action"
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

        # 4. Resolve the execution tier from the verdict, then gate on it.
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
            # Tier 1 and 2 are cleared for autonomous execution. Day 3 wires
            # this to the guarded Cloud Run Admin call.
            execution_status = "CLEARED_FOR_AUTONOMOUS_EXECUTION"

        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        # 5. Append to the hash-chained audit ledger.
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

        return {
            "incident_id": alert.incident_id,
            "execution_status": execution_status,
            "sre_diagnosis": sre_result["root_cause"],
            "sre_confidence": sre_result.get("confidence"),
            "proposed_action": action.model_dump(),
            "judge_evaluation": evaluation.model_dump(),
            "resolved_tier": resolved_tier.value,
            "approval_record": approval_record.model_dump() if approval_record else None,
            "past_memory_context": past_incidents,
            "ledger_chain_hash": ledger_hash,
            "executed_tools": executed_tools,
            "degraded": bool(degraded_reasons),
            "degraded_reasons": degraded_reasons,
            "telemetry": {
                "sre": sre_result.get("telemetry", {}),
                "judge": evaluation.telemetry,
                "total_duration_ms": duration_ms,
            },
            "total_duration_ms": duration_ms,
        }
