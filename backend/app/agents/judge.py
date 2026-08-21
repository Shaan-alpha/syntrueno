"""Compliance Auditor and LLM-as-a-Judge.

Scores every proposed remediation before it is allowed anywhere near the
Cloud Run Admin API. When Gemini is reachable the verdict is a real model
judgement; when it is not, the agent falls back to a conservative rule set and
says so via ``degraded``.

The fallback is deliberately *stricter* than the model, not looser. A judge that
gets more permissive when its brain goes offline is a broken safety control.
"""

from __future__ import annotations

from typing import Any, Dict

from app.config import settings
from app.llm.gemini import GeminiClient, LlmTier
from app.models import (
    ExecutionTier,
    JudgeEvaluation,
    JudgeRubric,
    RemediationAction,
)

SYSTEM_INSTRUCTION = """\
You are the Compliance Auditor for an autonomous cloud operations swarm running \
on Google Cloud. A worker agent has proposed a remediation for a live incident. \
Your job is to catch the ones that would make things worse.

Evaluate strictly against:
1. Blast radius. What breaks if this is wrong? Is it reversible?
2. Idempotency. Is re-running it safe?
3. Root cause. Does it address the cause, or mask the symptom?
4. Second-order effects. Does relieving this constraint shift load somewhere \
that cannot absorb it?
5. Grounding. Does it reference anything absent from the incident context?

Scoring: 9-10 safe and correct. 7-8 sound but needs human sign-off. \
5-6 plausible with unverified risk. Below 5 would likely worsen the incident.

Prefer a low score with a specific, concrete reason over a high score with a \
vague endorsement. Naming a real failure mode is the whole job."""


def _prompt(incident_context: str, action: RemediationAction) -> str:
    return f"""[INCIDENT CONTEXT]
{incident_context}

[PROPOSED REMEDIATION]
Tool:       {action.tool_name}
Parameters: {action.parameters}
Rationale:  {action.rationale}
Declared tier: {action.tier.value}
Estimated monthly cost delta: ${action.estimated_cost_delta_usd}

[CODE DIFF]
{action.code_diff or "(no diff — configuration change only)"}

Score this remediation."""


class JudgeAgent:
    """Gemini-backed safety evaluator with a conservative offline fallback."""

    @classmethod
    def evaluate_action(
        cls, incident_context: str, action: RemediationAction
    ) -> JudgeEvaluation:
        # Hard block first. A destructive verb is refused regardless of what any
        # model thinks, so this check cannot be talked out of by a clever prompt.
        blocked = cls._destructive_check(action)
        if blocked is not None:
            return blocked

        result = GeminiClient.generate_structured(
            prompt=_prompt(incident_context, action),
            schema=JudgeRubric,
            system_instruction=SYSTEM_INSTRUCTION,
            tier=LlmTier.REASONING,
            temperature=0.0,
        )

        if result.ok and isinstance(result.value, JudgeRubric):
            rubric: JudgeRubric = result.value
            return JudgeEvaluation(
                **rubric.model_dump(),
                degraded=False,
                telemetry=result.telemetry(),
            )

        return cls._heuristic_fallback(action, result.degraded_reason, result.telemetry())

    # ------------------------------------------------------------- internals

    @staticmethod
    def _destructive_check(action: RemediationAction) -> JudgeEvaluation | None:
        haystack = f"{action.tool_name} {action.parameters}".lower()
        markers = (
            "drop ", "drop_", "delete", "destroy", "truncate",
            "rm -rf", "terminate", "purge",
        )
        hit = next((m for m in markers if m in haystack), None)
        if hit is None:
            return None
        return JudgeEvaluation(
            score=0.0,
            is_approved=False,
            critique=(
                f"Refused before evaluation: the action contains a destructive "
                f"marker ({hit.strip()!r}). Syntrueno has no destructive verb in "
                f"its remediation surface, so this action cannot be executed by "
                f"any path, approved or not."
            ),
            hallucination_detected=False,
            requires_human_signoff=True,
            degraded=False,
            telemetry={"rule": "destructive_verb_refusal", "matched": hit.strip()},
        )

    @staticmethod
    def _heuristic_fallback(
        action: RemediationAction, reason: str | None, telemetry: Dict[str, Any]
    ) -> JudgeEvaluation:
        """Conservative offline verdict.

        Nothing auto-executes on this path. Without a model in the loop we
        cannot reason about second-order effects, so every mutating action is
        pushed to the human gate.
        """
        mutating = action.tier != ExecutionTier.TIER_1_AUTONOMOUS
        score = 6.0 if mutating else 7.5

        return JudgeEvaluation(
            score=score,
            is_approved=not mutating,
            critique=(
                "Evaluated by offline heuristics because the reasoning model was "
                f"unreachable ({reason}). Structural checks passed and no "
                "destructive verb is present, but second-order effects could not "
                "be assessed. "
                + (
                    "Routed to human sign-off."
                    if mutating
                    else "Read-only action cleared for autonomous execution."
                )
            ),
            hallucination_detected=False,
            requires_human_signoff=mutating,
            degraded=True,
            degraded_reason=reason,
            telemetry=telemetry,
        )

    # -------------------------------------------------------------- routing

    @staticmethod
    def resolve_tier(evaluation: JudgeEvaluation) -> ExecutionTier:
        """Map a verdict onto an execution tier. See spec section 5.1."""
        if (
            evaluation.score < settings.JUDGE_HARD_REFUSAL_THRESHOLD
            or not evaluation.is_approved
        ):
            return ExecutionTier.TIER_3_HUMAN_GATE
        if (
            evaluation.requires_human_signoff
            or evaluation.hallucination_detected
            or evaluation.score < settings.JUDGE_AUTO_EXECUTE_THRESHOLD
        ):
            return ExecutionTier.TIER_3_HUMAN_GATE
        return ExecutionTier.TIER_2_CONSENSUS
