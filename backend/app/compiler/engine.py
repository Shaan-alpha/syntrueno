"""ThorForja: turns tool sequences the swarm keeps repeating into reusable skills.

Two things this module is careful about, because the earlier version was not.

**A compiled skill replaces the diagnosis, never the authorisation.** Skipping
the SRE call is the legitimate saving: after the same sequence has resolved the
same class of incident several times, asking a model to derive it again is the
part that stopped being useful. Skipping the *Judge* would be something else
entirely -- it would make ThorForja a path around every guard the rest of the
system enforces, reachable by anyone who could get a pattern to recur. So
:meth:`propose` returns a proposed action, and that action goes through
judgement, tiering, and the human gate exactly as a model-derived one does.
The saving is one diagnosis call, and that is the only saving claimed.

**Every number is measured or absent.** The previous implementation reported
``latency_ms: 11.8`` and ``execution_time_ms: 12.5`` as constants, credited
itself ``3200`` tokens saved per call from a comment reading "approx", and set
``verified_by_judge=True`` on every manifest it ever built. It also returned
``COMPILED_SKILL_SUCCESS`` with a populated ``executed_tools`` list without
executing anything. Latency now comes from ``perf_counter``, token savings from
the diagnosis calls actually recorded against the cluster, and
``verified_by_judge`` from whether the Judge approved every trajectory in it.
"""

from __future__ import annotations

import logging
import time
from statistics import mean
from typing import Any, Dict, List, Optional

from app.compiler.recorder import TrajectoryRecorder
from app.models import AgentRole, AgentSkill, CompiledSkillManifest
from app.registry.a2a import AgentRegistry

logger = logging.getLogger(__name__)


class ThorForjaEngine:
    """Mines recurring tool skeletons into deterministic proposals."""

    _compiled_skills: Dict[str, CompiledSkillManifest] = {}

    # ------------------------------------------------------------- mining

    @classmethod
    def mine_and_compile(cls, min_occurrences: int = 2) -> List[CompiledSkillManifest]:
        """Compile skeletons seen across at least ``min_occurrences`` incidents."""
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for traj in TrajectoryRecorder.get_all_trajectories():
            sequence = traj.get("tool_sequence") or []
            if not sequence:
                continue
            clusters.setdefault("->".join(sequence), []).append(traj)

        newly_compiled: List[CompiledSkillManifest] = []
        for signature, cluster in clusters.items():
            if signature in cls._compiled_skills:
                continue

            # Counted by incident, not by row. Re-running one incident, or a
            # Pub/Sub redelivery that slipped through, would otherwise look
            # exactly like a pattern that recurs.
            incident_ids = {
                t.get("incident_id") for t in cluster if t.get("incident_id")
            }
            distinct = len(incident_ids) if incident_ids else len(cluster)
            if distinct < min_occurrences:
                continue

            manifest = cls._compile(signature, cluster, distinct)
            cls._compiled_skills[signature] = manifest
            newly_compiled.append(manifest)
            cls._publish(manifest)

        return newly_compiled

    @classmethod
    def _compile(
        cls, signature: str, cluster: List[Dict[str, Any]], distinct: int
    ) -> CompiledSkillManifest:
        sequence = cluster[0]["tool_sequence"]

        # Slots common to every occurrence. A key only some runs carried is not
        # part of the shape of this skill.
        slots = set(cluster[0].get("parameters") or {})
        for traj in cluster[1:]:
            slots &= set(traj.get("parameters") or {})

        scores = [
            t["judge_score"] for t in cluster if t.get("judge_score") is not None
        ]
        # Unknown is not approved. A trajectory recorded before judgement was
        # captured says nothing about safety, and defaulting it to approved is
        # how the old manifest came to claim verification it never had.
        verified = bool(cluster) and all(
            t.get("judge_approved") is True for t in cluster
        )

        token_counts = [
            t["diagnosis_tokens"]
            for t in cluster
            if isinstance(t.get("diagnosis_tokens"), int)
        ]

        return CompiledSkillManifest(
            skill_id=f"compiled-{signature.replace('->', '-').lower()}",
            skeleton_signature=signature,
            tool_sequence=sequence,
            input_slots=sorted(slots),
            # The checks that genuinely run before this sequence can mutate
            # anything, named so the manifest describes the real path rather
            # than a plausible-looking one.
            safety_preconditions=[
                "model_armor.screen_tool_invocation",
                "runadmin.project_pin",
                "runadmin.service_allowlist",
                "runadmin.verb_allowlist",
                "judge.evaluate_action",
                "human_gate.binding",
            ],
            verified_by_judge=verified,
            occurrences=len(cluster),
            distinct_incidents=distinct,
            min_judge_score=min(scores) if scores else None,
            mean_diagnosis_tokens=int(mean(token_counts)) if token_counts else 0,
        )

    @classmethod
    def _publish(cls, manifest: CompiledSkillManifest) -> None:
        """Advertise the skill on the SRE agent's card."""
        AgentRegistry.register_compiled_skill_for_role(
            role=AgentRole.SRE,
            skill=AgentSkill(
                name=f"compiled_{manifest.skill_id}",
                description=(
                    f"Deterministic proposal for [{manifest.skeleton_signature}], "
                    f"mined from {manifest.distinct_incidents} incidents. "
                    "Skips the diagnosis call; still judged and gated."
                ),
                input_schema={
                    "type": "object",
                    "properties": {k: {"type": "string"} for k in manifest.input_slots},
                },
                is_compiled_skill=True,
                # Left unset: this skill has never run, so there is no
                # execution time to report yet.
                execution_time_ms=None,
            ),
        )

    # ---------------------------------------------------------- dispatch

    @classmethod
    def propose(
        cls, skeleton_sig: str, inputs: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Derive the action this skill stands for, without calling a model.

        Returns a *proposal*. It is not an execution and it is not an
        authorisation: the caller still has to put it through the Judge and the
        gate. ``None`` when no skill matches the signature.
        """
        manifest = cls._compiled_skills.get(skeleton_sig)
        if manifest is None:
            return None

        started = time.perf_counter()
        missing = [slot for slot in manifest.input_slots if slot not in inputs]
        parameters = {
            slot: inputs[slot] for slot in manifest.input_slots if slot in inputs
        }
        elapsed_ms = (time.perf_counter() - started) * 1000

        if missing:
            # Refused rather than filled in. Guessing a service id is how a
            # skill mined against the canary ends up pointed at something else.
            logger.info(
                "Compiled skill %s refused: missing %s", manifest.skill_id, missing
            )
            return {
                "skill_id": manifest.skill_id,
                "status": "REFUSED_INCOMPLETE_INPUTS",
                "missing_slots": missing,
                "latency_ms": round(elapsed_ms, 4),
                "llm_calls_made": 0,
            }

        manifest.total_executions += 1
        manifest.total_tokens_saved += manifest.mean_diagnosis_tokens

        return {
            "skill_id": manifest.skill_id,
            # Not "SUCCESS": nothing has been executed and nothing approved.
            "status": "PROPOSED",
            "proposed_tools": manifest.tool_sequence,
            "parameters": parameters,
            "llm_calls_made": 0,
            "latency_ms": round(elapsed_ms, 4),
            # The mean of the diagnosis calls this skill replaces. Zero when
            # the cluster predates token recording -- zero being the honest
            # answer when nothing was measured.
            "tokens_saved": manifest.mean_diagnosis_tokens,
            "verified_by_judge": manifest.verified_by_judge,
            "requires_judgement": True,
            "requires_human_gate_if_tier_3": True,
            "total_skill_executions": manifest.total_executions,
        }

    @classmethod
    def list_compiled_skills(cls) -> List[CompiledSkillManifest]:
        return list(cls._compiled_skills.values())

    @classmethod
    def clear(cls) -> None:
        """Test helper: drop all compiled skills."""
        cls._compiled_skills.clear()
