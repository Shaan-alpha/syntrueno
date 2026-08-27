"""Syntrueno - Zero-Trust Autonomous Cloud Operations Swarm with ThorForja Self-Compiling Engine."""

# Read from Settings rather than restated here. These were two literals that
# had drifted apart -- this file said 1.0.0 while config.py said 2.0.0, and
# config.py is the one the API serves on /api/v1/health and /docs. A version
# number that disagrees with itself is worse than one that is merely stale,
# because whichever a reader finds first looks authoritative.
from app.config import settings

__version__ = settings.VERSION
