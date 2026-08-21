# Documentation

## Current

| Document | What it is |
| :-- | :-- |
| [System design](specs/2026-08-22-live-system-design.md) | Architecture, guardrails, verified environment facts, day plan |
| [Submission package](SUBMISSION_PACKAGE.md) | Devpost copy, architecture diagram, video script |
| [README](../README.md) | What the system does today — **authoritative** |

## Research (pre-build)

`01`–`16` are strategy and research written on 2026-08-21, before implementation.
They record planning and intent, and several describe features as though built
that were not. Each carries a banner saying so. Where they disagree with the
README, the code is authoritative.

Two corrections apply across the set:

- `gemini-2.5-*` returns **404 for new API keys**. Live routing is
  `gemini-3.1-flash-lite` and `gemini-3.6-flash`.
- Track-density percentages (55/30/15 in some documents, 45/35/20 in others) are
  an unsourced working hypothesis, not measured data. They must not be stated as
  fact in any submission.

> **[`12_COMPETITIVE_LANDSCAPE_AND_GAP_ANALYSIS.md`](12_COMPETITIVE_LANDSCAPE_AND_GAP_ANALYSIS.md)
> is internal only.** It names real competitor repositories and critiques them.
> It must not appear in the Devpost writeup, the video, or any public material.
