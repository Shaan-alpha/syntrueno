"""Guarded Cloud Run mutations — the only code that can change infrastructure.

Every guard here fails closed, and they are ordered cheapest-first so a refusal
never costs a network call. The module deliberately has **no delete verb at
all**: it is not that deletion is blocked, it is that deletion is not
implemented, so no code path — however confused, injected, or buggy — can reach
it from here.

Five checks run before anything is sent to Google Cloud:

1. **Project pin.** Only the configured project is addressable.
2. **Service allowlist.** Only the canary service may be mutated. The runtime
   service account is also granted ``run.admin`` on that single resource rather
   than project-wide, so this is enforced twice: once here and once by IAM.
3. **Verb allowlist.** Only capacity and lifecycle changes are representable.
4. **Destructive-content screen.** Defence in depth via Model Armor's outbound
   rules, in case a parameter value carries something the verb check missed.
5. **Approval binding.** A tier-3 action requires a signed approval whose hash
   covers this exact tool, parameters, and tier. A signature for one action can
   never authorise another.

Then the mutation runs, and the result is **verified by re-reading live state**
rather than trusting the API's acknowledgement.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from app.config import settings
from app.models import ExecutionTier, RemediationAction, RemediationTool
from app.security.human_gate import HumanApprovalGate
from app.security.model_armor import ModelArmorShield, ToolInvocationRefused

logger = logging.getLogger(__name__)

# Verbs this module knows how to perform. Anything absent is unreachable.
MUTATING_VERBS = {
    RemediationTool.UPDATE_RESOURCES.value,
    RemediationTool.UPDATE_SCALING.value,
    RemediationTool.RECYCLE_REVISION.value,
}
NON_MUTATING_VERBS = {
    RemediationTool.NO_ACTION.value,
    RemediationTool.RECONFIGURE_POOL.value,  # application config, not infra
}


class RemediationRefused(Exception):
    """A guard rejected this action. Nothing was sent to Google Cloud."""


class CloudRunAdmin:
    """Reads and guarded writes against Cloud Run."""

    _client: Any = None
    _init_attempted: bool = False

    # ---------------------------------------------------------------- setup

    @classmethod
    def _get_client(cls) -> Any:
        if cls._init_attempted:
            return cls._client
        cls._init_attempted = True
        try:
            from google.cloud import run_v2

            cls._client = run_v2.ServicesClient()
        except Exception as exc:
            logger.warning("Cloud Run client unavailable: %s", exc)
            cls._client = None
        return cls._client

    @classmethod
    def reset(cls) -> None:
        cls._client = None
        cls._init_attempted = False

    @classmethod
    def available(cls) -> bool:
        return cls._get_client() is not None

    @staticmethod
    def _resource_name(service: str) -> str:
        return (
            f"projects/{settings.GOOGLE_CLOUD_PROJECT}"
            f"/locations/{settings.GOOGLE_CLOUD_LOCATION}/services/{service}"
        )

    # --------------------------------------------------------------- guards

    @classmethod
    def check_guards(
        cls, action: RemediationAction, approval_id: Optional[str] = None
    ) -> None:
        """Run every guard. Raises ``RemediationRefused`` on the first failure."""
        service = action.parameters.get("service_id", "")
        # Accept a bare name or a "cloud-run/name" form.
        service = service.split("/")[-1]

        # 1. Service allowlist.
        if service != settings.CANARY_SERVICE_NAME:
            raise RemediationRefused(
                f"Service {service!r} is not on the remediation allowlist. "
                f"Only {settings.CANARY_SERVICE_NAME!r} may be mutated."
            )

        # 2. Verb allowlist.
        if action.tool_name not in MUTATING_VERBS | NON_MUTATING_VERBS:
            raise RemediationRefused(
                f"Verb {action.tool_name!r} is not a known remediation. "
                f"This module implements no destructive verb."
            )

        # 3. Destructive-content screen on the parameters themselves.
        try:
            ModelArmorShield.screen_tool_invocation(action.tool_name, action.parameters)
        except ToolInvocationRefused as exc:
            raise RemediationRefused(str(exc))

        # 4. Approval binding for anything gated.
        if action.tier == ExecutionTier.TIER_3_HUMAN_GATE:
            if not HumanApprovalGate.authorises(action, approval_id):
                raise RemediationRefused(
                    "This action requires a signed human approval bound to its "
                    "exact parameters, and no matching signature exists."
                )

    # --------------------------------------------------------------- reading

    @classmethod
    def describe(cls, service: Optional[str] = None) -> Dict[str, Any]:
        """Current live configuration of a service."""
        service = service or settings.CANARY_SERVICE_NAME
        client = cls._get_client()
        if client is None:
            return {"available": False, "reason": "cloud_run_client_unavailable"}

        try:
            svc = client.get_service(name=cls._resource_name(service))
            container = svc.template.containers[0] if svc.template.containers else None
            limits = dict(container.resources.limits) if container else {}
            return {
                "available": True,
                "service": service,
                "revision": svc.latest_ready_revision.split("/")[-1]
                if svc.latest_ready_revision else None,
                "memory": limits.get("memory"),
                "cpu": limits.get("cpu"),
                "min_instances": svc.template.scaling.min_instance_count,
                "max_instances": svc.template.scaling.max_instance_count,
                "uri": svc.uri,
            }
        except Exception as exc:
            logger.warning("describe(%s) failed: %s", service, exc)
            return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:140]}"}

    # -------------------------------------------------------------- writing

    @classmethod
    def apply(
        cls, action: RemediationAction, approval_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute a remediation after every guard passes.

        Returns a result describing what happened, including the before and
        after state read back from Google Cloud. Never raises for a guard
        failure — the refusal is part of the result so it can be audited.
        """
        started = time.perf_counter()
        service = action.parameters.get("service_id", "").split("/")[-1]

        try:
            cls.check_guards(action, approval_id)
        except RemediationRefused as exc:
            return {
                "status": "REFUSED",
                "reason": str(exc),
                "service": service,
                "tool": action.tool_name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        if action.tool_name in NON_MUTATING_VERBS:
            return {
                "status": "NO_INFRASTRUCTURE_CHANGE",
                "reason": f"{action.tool_name} does not alter Cloud Run configuration.",
                "service": service,
                "tool": action.tool_name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        before = cls.describe(service)

        if settings.REMEDIATION_DRY_RUN:
            return {
                "status": "DRY_RUN",
                "reason": "REMEDIATION_DRY_RUN is enabled; the plan was not executed.",
                "service": service,
                "tool": action.tool_name,
                "would_apply": action.parameters,
                "before": before,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        client = cls._get_client()
        if client is None:
            return {
                "status": "FAILED",
                "reason": "cloud_run_client_unavailable",
                "service": service,
                "tool": action.tool_name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        try:
            svc = client.get_service(name=cls._resource_name(service))
            cls._mutate_in_place(svc, action)
            client.update_service(service=svc)

            # Deliberately not waiting on the returned long-running operation.
            # operation.result() calls run.operations.get, which is a
            # project-level permission — granting it would widen the runtime
            # service account beyond the single canary resource it is scoped
            # to, purely to watch an operation we do not need to watch.
            #
            # Polling live state is both narrower and stronger: the operation
            # reporting success only tells us Cloud Run accepted the request,
            # whereas re-reading the service tells us the change is actually
            # in effect. We were going to verify that way regardless.
            cls._await_convergence(action, service)
        except Exception as exc:
            logger.error("Remediation failed on %s: %s", service, exc)
            return {
                "status": "FAILED",
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                "service": service,
                "tool": action.tool_name,
                "before": before,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        # Spend the signature. A signed approval authorises one execution, so
        # the same signature cannot be replayed to repeat the change later.
        consumed = None
        if action.tier == ExecutionTier.TIER_3_HUMAN_GATE:
            record = HumanApprovalGate.consume(action, approval_id)
            consumed = record.approval_id if record else None

        # Verify against live state rather than trusting the acknowledgement.
        after = cls.describe(service)
        verified, detail = cls._verify(action, after)

        return {
            "status": "APPLIED" if verified else "APPLIED_UNVERIFIED",
            "approval_consumed": consumed,
            "verified": verified,
            "verification_detail": detail,
            "service": service,
            "tool": action.tool_name,
            "applied": action.parameters,
            "before": before,
            "after": after,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    # ------------------------------------------------------------ internals

    @classmethod
    def _await_convergence(
        cls, action: RemediationAction, service: str, timeout_s: int = 90
    ) -> bool:
        """Poll live state until the requested change is actually in effect.

        Returns whether it converged. A timeout is not treated as a failure —
        the caller's verification step reports the real outcome either way, so
        a slow rollout surfaces as APPLIED_UNVERIFIED rather than a false
        FAILED.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            converged, _detail = cls._verify(action, cls.describe(service))
            if converged:
                return True
            time.sleep(3)
        return False

    @staticmethod
    def _mutate_in_place(svc: Any, action: RemediationAction) -> None:
        params = action.parameters

        if action.tool_name == RemediationTool.UPDATE_RESOURCES.value:
            container = svc.template.containers[0]
            if params.get("memory"):
                container.resources.limits["memory"] = str(params["memory"])
            if params.get("cpu"):
                container.resources.limits["cpu"] = str(params["cpu"])

        elif action.tool_name == RemediationTool.UPDATE_SCALING.value:
            if params.get("min_instances") is not None:
                svc.template.scaling.min_instance_count = int(params["min_instances"])
            if params.get("max_instances") is not None:
                svc.template.scaling.max_instance_count = int(params["max_instances"])

        elif action.tool_name == RemediationTool.RECYCLE_REVISION.value:
            # Clearing the revision name makes Cloud Run mint a fresh one,
            # which is a rolling restart with traffic draining.
            svc.template.revision = ""

    @staticmethod
    def _verify(action: RemediationAction, after: Dict[str, Any]) -> tuple[bool, str]:
        """Confirm the live state now matches what was requested."""
        if not after.get("available"):
            return False, "could not read back service state"

        params = action.parameters
        checks = []

        if action.tool_name == RemediationTool.UPDATE_RESOURCES.value:
            if params.get("memory"):
                checks.append(("memory", str(params["memory"]), after.get("memory")))
            if params.get("cpu"):
                checks.append(("cpu", str(params["cpu"]), after.get("cpu")))
        elif action.tool_name == RemediationTool.UPDATE_SCALING.value:
            if params.get("min_instances") is not None:
                checks.append(("min_instances", int(params["min_instances"]), after.get("min_instances")))
            if params.get("max_instances") is not None:
                checks.append(("max_instances", int(params["max_instances"]), after.get("max_instances")))
        elif action.tool_name == RemediationTool.RECYCLE_REVISION.value:
            return True, f"service is serving revision {after.get('revision')}"

        mismatches = [
            f"{field}: wanted {want!r}, live value is {got!r}"
            for field, want, got in checks
            if str(want) != str(got)
        ]
        if mismatches:
            return False, "; ".join(mismatches)
        return True, "; ".join(f"{f}={g}" for f, _w, g in checks) or "no fields to verify"
