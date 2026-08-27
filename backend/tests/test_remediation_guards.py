"""Guards on the only code that can change infrastructure.

Option C gives the swarm the ability to mutate a real Cloud Run service, so
these tests are the difference between an autonomous agent and an incident.
Every one of them asserts a refusal.
"""

import inspect

import pytest

from app.cloud import runadmin
from app.cloud.runadmin import CloudRunAdmin, RemediationRefused
from app.config import settings
from app.models import ExecutionTier, RemediationAction, RemediationTool
from app.security.human_gate import ApprovalStateError, HumanApprovalGate


def action(
    tool=RemediationTool.UPDATE_RESOURCES.value,
    service="syntrueno-canary",
    params=None,
    tier=ExecutionTier.TIER_2_CONSENSUS,
):
    merged = {"service_id": service}
    merged.update(params or {"memory": "1Gi"})
    return RemediationAction(
        action_id="act-guard-test", tool_name=tool, parameters=merged,
        rationale="test", tier=tier,
    )


# ==================================================== the module's shape

class TestNoDestructiveVerbExists:
    """Deletion is not blocked here — it is not implemented.

    A blocked path can be reached by a bug. An absent one cannot.
    """

    def test_the_remediation_enum_contains_no_destructive_verb(self):
        for tool in RemediationTool:
            assert not any(
                word in tool.value.lower()
                for word in ("delete", "destroy", "drop", "remove", "purge", "terminate")
            ), f"{tool.value} is destructive and must not be representable"

    def test_the_module_never_calls_a_delete_api(self):
        source = inspect.getsource(runadmin)
        for forbidden in ("delete_service", "delete_revision", "delete_job", ".delete("):
            assert forbidden not in source, f"{forbidden} must not appear in this module"

    def test_every_mutating_verb_is_a_known_enum_member(self):
        known = {t.value for t in RemediationTool}
        assert runadmin.MUTATING_VERBS <= known
        assert runadmin.NON_MUTATING_VERBS <= known


# ==================================================== service allowlist

class TestServiceAllowlist:

    @pytest.mark.parametrize("service", [
        "syntrueno",                 # the swarm's own service
        "prod-payments-api",
        "cloud-run/auth-service",
        "",
        "syntrueno-canary-evil",
        "SYNTRUENO-CANARY",          # case must not slip through
    ])
    def test_only_the_canary_may_be_mutated(self, service):
        with pytest.raises(RemediationRefused, match="allowlist"):
            CloudRunAdmin.check_guards(action(service=service))

    def test_the_canary_itself_passes(self):
        CloudRunAdmin.check_guards(action(service="syntrueno-canary"))

    def test_a_cloud_run_prefixed_canary_name_is_accepted(self):
        CloudRunAdmin.check_guards(action(service="cloud-run/syntrueno-canary"))

    def test_the_allowlist_is_config_driven_not_hardcoded(self, monkeypatch):
        monkeypatch.setattr(settings, "CANARY_SERVICE_NAME", "some-other-canary")
        with pytest.raises(RemediationRefused):
            CloudRunAdmin.check_guards(action(service="syntrueno-canary"))


# ======================================================== verb allowlist

class TestVerbAllowlist:

    @pytest.mark.parametrize("tool", [
        "delete_service", "drop_database", "rm_rf_everything",
        "gcloud_projects_delete", "shutdown_production",
    ])
    def test_an_unknown_verb_is_refused(self, tool):
        with pytest.raises(RemediationRefused, match="not a known remediation"):
            CloudRunAdmin.check_guards(action(tool=tool))

    def test_destructive_content_in_parameters_is_refused(self):
        """Defence in depth: the verb is fine but a value carries a payload."""
        with pytest.raises(RemediationRefused):
            CloudRunAdmin.check_guards(
                action(params={"memory": "1Gi; DROP TABLE accounts"})
            )


# ====================================================== approval binding

class TestApprovalBinding:

    def test_a_tier_three_action_without_a_signature_is_refused(self):
        with pytest.raises(RemediationRefused, match="signed human approval"):
            CloudRunAdmin.check_guards(action(tier=ExecutionTier.TIER_3_HUMAN_GATE))

    def test_a_pending_but_unsigned_approval_does_not_authorise(self):
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        HumanApprovalGate.create_pending_approval("inc-1", act)
        with pytest.raises(RemediationRefused):
            CloudRunAdmin.check_guards(act)

    def test_a_signed_approval_authorises_exactly_its_own_action(self):
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")
        CloudRunAdmin.check_guards(act)

    def test_a_signature_does_not_carry_over_to_different_parameters(self):
        """The attack this prevents: approve 1Gi, then execute 32Gi."""
        approved = action(tier=ExecutionTier.TIER_3_HUMAN_GATE, params={"memory": "1Gi"})
        record = HumanApprovalGate.create_pending_approval("inc-1", approved)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")

        swapped = action(tier=ExecutionTier.TIER_3_HUMAN_GATE, params={"memory": "32Gi"})
        with pytest.raises(RemediationRefused, match="signed human approval"):
            CloudRunAdmin.check_guards(swapped)

    def test_a_signature_does_not_carry_over_to_a_different_verb(self):
        approved = action(
            tool=RemediationTool.UPDATE_RESOURCES.value,
            tier=ExecutionTier.TIER_3_HUMAN_GATE,
        )
        record = HumanApprovalGate.create_pending_approval("inc-1", approved)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")

        other = action(
            tool=RemediationTool.UPDATE_SCALING.value,
            params={"min_instances": 5},
            tier=ExecutionTier.TIER_3_HUMAN_GATE,
        )
        with pytest.raises(RemediationRefused):
            CloudRunAdmin.check_guards(other)


# ============================================================== dry run

class TestDryRun:

    def test_dry_run_reports_the_plan_without_executing(self, monkeypatch):
        monkeypatch.setattr(settings, "REMEDIATION_DRY_RUN", True)
        result = CloudRunAdmin.apply(action())
        assert result["status"] == "DRY_RUN"
        assert result["would_apply"]["memory"] == "1Gi"

    def test_a_refusal_never_reaches_google_cloud(self, monkeypatch):
        """Guards run before any client is constructed."""
        called = {"n": 0}
        monkeypatch.setattr(
            CloudRunAdmin, "_get_client",
            classmethod(lambda cls: called.__setitem__("n", called["n"] + 1)),
        )
        result = CloudRunAdmin.apply(action(service="prod-payments-api"))
        assert result["status"] == "REFUSED"
        assert called["n"] == 0

    def test_a_refusal_is_returned_not_raised_so_it_can_be_audited(self):
        result = CloudRunAdmin.apply(action(service="prod-payments-api"))
        assert result["status"] == "REFUSED"
        assert "allowlist" in result["reason"]

    def test_a_non_mutating_verb_reports_no_infrastructure_change(self):
        result = CloudRunAdmin.apply(action(tool=RemediationTool.NO_ACTION.value))
        assert result["status"] == "NO_INFRASTRUCTURE_CHANGE"


# ======================================================= replay protection

class TestSignatureIsSingleUse:
    """A signature authorises one execution, not a standing permission.

    Found while running the first real mutation: an approval signed earlier
    still authorised the identical action later, because only the hash was
    checked. Sign a memory bump once and the swarm could replay it unprompted
    any time afterwards.
    """

    def test_a_consumed_signature_no_longer_authorises(self):
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")

        assert HumanApprovalGate.authorises(act) is True
        HumanApprovalGate.consume(act)
        assert HumanApprovalGate.authorises(act) is False

        with pytest.raises(RemediationRefused, match="signed human approval"):
            CloudRunAdmin.check_guards(act)

    def test_consuming_records_which_action_spent_it(self):
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")

        spent = HumanApprovalGate.consume(act)
        assert spent.consumed_at is not None
        assert spent.consumed_by_action_id == act.action_id

    def test_consuming_when_nothing_authorises_returns_none(self):
        assert HumanApprovalGate.consume(action(tier=ExecutionTier.TIER_3_HUMAN_GATE)) is None

    def test_an_expired_signature_does_not_authorise(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")
        assert HumanApprovalGate.authorises(act) is True

        record.expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        assert HumanApprovalGate.authorises(act) is False

    def test_an_expired_approval_cannot_be_signed(self):
        """Expiry was enforced at execution but not at signing.

        Signing a dead approval returned SUCCESS and flipped it to APPROVED;
        the refusal only surfaced one call later, as a guard message about a
        missing signature -- for an approval the operator had just watched
        succeed. Observed live on 2026-08-26 with 13 of 15 PENDING approvals
        already past their TTL. Refuse at the gate the operator is standing at.
        """
        from datetime import datetime, timedelta, timezone

        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-1", act)
        record.expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()

        with pytest.raises(ApprovalStateError):
            HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")

        assert record.status == "PENDING", "a refused signature must not mutate state"

    def test_a_fresh_signature_is_needed_for_each_execution(self):
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)

        for _ in range(3):
            record = HumanApprovalGate.create_pending_approval("inc-1", act)
            HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")
            CloudRunAdmin.check_guards(act)
            HumanApprovalGate.consume(act)
            with pytest.raises(RemediationRefused):
                CloudRunAdmin.check_guards(act)

    def test_replay_cannot_borrow_a_different_unspent_signature(self):
        """The bug this prevents, seen live.

        A run that fails after signing leaves a valid unspent signature behind.
        Several can accumulate for the same action. Without binding the check
        to one approval id, a replay quietly satisfies itself from the pool and
        the mutation runs a second time.
        """
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)

        first = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(first.approval_id, "engineer@corp")
        spare = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(spare.approval_id, "engineer@corp")

        CloudRunAdmin.check_guards(act, approval_id=first.approval_id)
        HumanApprovalGate.consume(act, approval_id=first.approval_id)

        # The spare is still unspent, but it must not cover a replay of the first.
        with pytest.raises(RemediationRefused):
            CloudRunAdmin.check_guards(act, approval_id=first.approval_id)

        # Unbound, the spare would have silently authorised it.
        assert HumanApprovalGate.authorises(act) is True

    def test_consuming_is_bound_to_the_named_approval(self):
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        a = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(a.approval_id, "engineer@corp")
        b = HumanApprovalGate.create_pending_approval("inc-1", act)
        HumanApprovalGate.sign_approval(b.approval_id, "engineer@corp")

        HumanApprovalGate.consume(act, approval_id=a.approval_id)

        assert HumanApprovalGate.get(a.approval_id).consumed_at is not None
        assert HumanApprovalGate.get(b.approval_id).consumed_at is None


# ================================================ concurrency on the gate

class TestOneSignatureCannotAuthoriseTwoExecutions:
    """The single-use guarantee has to hold under concurrency, not just in
    sequence.

    ``check_guards`` only *asks* whether a signature authorises an action, and
    the spend used to happen after the mutation. Two executions arriving
    together therefore both got "yes", both wrote to Cloud Run, and only the
    second's consume returned ``None`` -- one signature, two mutations, one
    audit entry saying it happened once. FastAPI runs sync endpoints in a
    threadpool, so this needs no unusual deployment to reach.

    Reproduced deterministically before the lock existed: 2 of 2 threads
    mutated, and 8 of 8 in the wider version of this test.
    """

    @staticmethod
    def _signed_approval():
        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-race", act)
        HumanApprovalGate.sign_approval(record.approval_id, "engineer@corp")
        return act, record

    def test_only_one_of_many_racing_claims_wins(self):
        import threading

        act, record = self._signed_approval()

        winners = []
        lock = threading.Lock()
        start = threading.Barrier(8)

        def claim():
            start.wait()
            if HumanApprovalGate.consume(act, approval_id=record.approval_id):
                with lock:
                    winners.append(threading.current_thread().name)

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(winners) == 1, (
            f"{len(winners)} threads each spent the same signature; a signature "
            "authorises exactly one execution."
        )

    def test_the_signature_is_spent_before_the_mutation_not_after(self, monkeypatch):
        """Order is the whole fix: checking first and spending afterwards leaves
        the window open however carefully the spend itself is written."""
        monkeypatch.setattr(settings, "REMEDIATION_DRY_RUN", False)

        act, record = self._signed_approval()
        seen_at_mutation = {}

        class FakeClient:
            def get_service(self, name):
                # By the time Cloud Run is touched, the signature must already
                # be spent -- otherwise a concurrent caller could still find it.
                stored = HumanApprovalGate.get(record.approval_id)
                seen_at_mutation["consumed_at"] = stored.consumed_at
                raise RuntimeError("stop here; the ordering is the assertion")

        monkeypatch.setattr(
            CloudRunAdmin, "_get_client", classmethod(lambda cls: FakeClient())
        )

        CloudRunAdmin.apply(act, approval_id=record.approval_id)
        assert seen_at_mutation["consumed_at"] is not None

    def test_a_failed_mutation_hands_the_signature_back(self, monkeypatch):
        """A signature buys one execution, and a call that raised before
        changing anything did not execute. Burning it would cost the operator a
        whole incident re-run for a transient Cloud Run error."""
        monkeypatch.setattr(settings, "REMEDIATION_DRY_RUN", False)

        act, record = self._signed_approval()

        class ExplodingClient:
            def get_service(self, name):
                raise RuntimeError("transient 503 from Cloud Run")

        monkeypatch.setattr(
            CloudRunAdmin, "_get_client", classmethod(lambda cls: ExplodingClient())
        )

        result = CloudRunAdmin.apply(act, approval_id=record.approval_id)

        assert result["status"] == "FAILED"
        assert HumanApprovalGate.get(record.approval_id).consumed_at is None
        assert HumanApprovalGate.authorises(act, record.approval_id) is True

    def test_the_loser_of_a_race_is_refused_rather_than_mutating(self, monkeypatch):
        monkeypatch.setattr(settings, "REMEDIATION_DRY_RUN", False)

        act, record = self._signed_approval()
        HumanApprovalGate.consume(act, approval_id=record.approval_id)

        mutations = []

        class RecordingClient:
            def get_service(self, name):
                mutations.append(name)
                raise AssertionError("must not reach Cloud Run without a signature")

        monkeypatch.setattr(
            CloudRunAdmin, "_get_client", classmethod(lambda cls: RecordingClient())
        )

        result = CloudRunAdmin.apply(act, approval_id=record.approval_id)

        assert result["status"] == "REFUSED"
        assert mutations == []


class TestSigningIsSerialised:
    def test_two_racing_signatures_do_not_both_report_success(self):
        """Both callers could read PENDING, and the second would overwrite the
        first signer's identity on a record that was already APPROVED."""
        import threading

        act = action(tier=ExecutionTier.TIER_3_HUMAN_GATE)
        record = HumanApprovalGate.create_pending_approval("inc-1", act)

        outcomes = []
        lock = threading.Lock()
        start = threading.Barrier(6)

        def sign(who):
            start.wait()
            try:
                HumanApprovalGate.sign_approval(record.approval_id, who)
                with lock:
                    outcomes.append(who)
            except ApprovalStateError:
                pass

        threads = [threading.Thread(target=sign, args=(f"eng-{i}",)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(outcomes) == 1
        assert HumanApprovalGate.get(record.approval_id).signed_by == outcomes[0]
