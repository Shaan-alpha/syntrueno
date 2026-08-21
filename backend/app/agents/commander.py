import time
from typing import Dict, Any, List
from app.models import IncidentAlert, IncidentSeverity, ExecutionTier
from app.agents.sre import SREAgent
from app.agents.finops import FinOpsAgent
from app.agents.judge import JudgeAgent
from app.storage.memory_bank import MemoryBank
from app.storage.audit_ledger import AuditLedger
from app.models import AuditLogEntry
from app.security.human_gate import HumanApprovalGate

class SentinelCommander:
    """Master Socratic Orchestrator coordinating the SentinelMesh multi-agent swarm."""
    
    @classmethod
    def process_incident(cls, alert: IncidentAlert, user_session: str = "sess-default") -> Dict[str, Any]:
        """Coordinates end-to-end incident triage across SRE, FinOps, and Auditor."""
        start_time = time.perf_counter()
        
        # 1. Query Persistent Memory Bank
        past_incidents = MemoryBank.query_similar_incidents(alert.service_id, limit=2)
        
        # 2. Dispatch to SRE Agent via A2A
        sre_result = SREAgent.diagnose_and_plan(alert)
        proposed_action = sre_result["remediation_action"]
        
        # 3. Dispatch to Judge Agent (LLM-as-a-Judge)
        evaluation = JudgeAgent.evaluate_action(
            incident_context=f"Alert: {alert.metric_name} on {alert.service_id}",
            action=proposed_action,
        )
        
        # 4. Handle Governance Gate
        approval_record = None
        if evaluation.requires_human_signoff:
            approval_record = HumanApprovalGate.create_pending_approval(alert.incident_id, proposed_action)
            execution_status = "AWAITING_HUMAN_SIGNATURE"
        else:
            execution_status = "AUTO_EXECUTED_IN_SANDBOX"
            
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        
        # 5. Record to Tamper-Evident Audit Ledger
        audit_entry = AuditLogEntry(
            event_id=f"evt-{alert.incident_id[-4:]}",
            session_id=user_session,
            agent_name="SentinelCommander",
            action_name=proposed_action.tool_name,
            status=execution_status,
            details={
                "incident_id": alert.incident_id,
                "judge_score": evaluation.score,
                "tier": proposed_action.tier.value,
            },
            duration_ms=duration_ms,
        )
        ledger_hash = AuditLedger.record_entry(audit_entry)
        
        return {
            "incident_id": alert.incident_id,
            "execution_status": execution_status,
            "sre_diagnosis": sre_result["root_cause"],
            "proposed_action": proposed_action.model_dump(),
            "judge_evaluation": evaluation.model_dump(),
            "approval_record": approval_record.model_dump() if approval_record else None,
            "past_memory_context": past_incidents,
            "ledger_chain_hash": ledger_hash,
            "total_duration_ms": duration_ms,
        }
