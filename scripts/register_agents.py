"""Publish every agent into Google's Agent Registry.

Track 3 asks that agents be catalogued for cross-department discovery. This is
that catalogue: the same A2A cards the service serves at
``/.well-known/agent-card.json``, stored in the registry so a client that has
never heard of this deployment can find them.

Driven from the live local registry rather than a hardcoded list, so it stays
correct as agents are added. Idempotent: an existing service is updated in
place rather than duplicated.

The card must be A2A **v1.0** or the registry refuses it outright -- see
``app/registry/agent_card.py`` for the four fields that decide it.

    python scripts/register_agents.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.registry.a2a import AgentRegistry            # noqa: E402
from app.registry.agent_card import (                  # noqa: E402
    registry_service_id as service_id,
    to_a2a_agent_card,
)

PROJECT = os.environ.get("PROJECT_ID", "composed-maxim-498517-f0")
LOCATION = os.environ.get("AGENT_REGISTRY_LOCATION", "us-central1")
BASE_URL = os.environ.get(
    "SERVICE_URL", "https://syntrueno-18489510475.us-central1.run.app"
)


# On Windows gcloud is a .cmd shim, and CreateProcess will not resolve a bare
# "gcloud" the way a shell would. Resolve it once, here, rather than passing
# shell=True and interpolating a JSON payload through a command line.
GCLOUD = shutil.which("gcloud") or shutil.which("gcloud.cmd") or "gcloud"


def _gcloud(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [GCLOUD, "agent-registry", "services", *args,
         f"--project={PROJECT}", f"--location={LOCATION}"],
        capture_output=True, text=True,
    )


def exists(sid: str) -> bool:
    return _gcloud("describe", sid, "--format=value(name)").returncode == 0


def main() -> int:
    cards = AgentRegistry.list_all_cards()
    if not cards:
        print("No agents in the local registry; nothing to publish.")
        return 1

    failures = 0
    for card in cards:
        sid = service_id(card.name)
        payload = json.dumps(to_a2a_agent_card(card, BASE_URL))
        verb = "update" if exists(sid) else "create"

        result = _gcloud(
            verb, sid,
            f"--display-name={card.name}",
            "--agent-spec-type=a2a-agent-card",
            f"--agent-spec-content={payload}",
        )
        print(f"  {verb:6} {sid:26} {'ok' if result.returncode == 0 else 'FAILED'}")
        if result.returncode != 0:
            failures += 1
            # The registry's validation errors name the offending field, which
            # is the whole diagnostic. Do not swallow them.
            print("         " + result.stderr.strip()[:500])

    print(
        f"\n{len(cards) - failures}/{len(cards)} agents published to "
        f"Agent Registry in {LOCATION}."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
