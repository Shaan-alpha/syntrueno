/**
 * Tests for the API client.
 *
 * Deliberately narrow. These cover the two things that actually went wrong in
 * this codebase: response fields read under the wrong name, and stream frames
 * assumed to arrive whole. Component rendering is not tested here — it was
 * never the source of a defect.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, streamIncident } from './api';
import type { StreamEvent } from './types';

function mockJson(body: unknown, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: 'x',
    json: async () => body,
  } as unknown as Response);
}

/** Build a readable stream that emits the given chunks verbatim. */
function mockStream(chunks: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          i < chunks.length
            ? { done: false, value: encoder.encode(chunks[i++]) }
            : { done: true, value: undefined },
      }),
    },
  } as unknown as Response);
}

afterEach(() => vi.unstubAllGlobals());

// ============================================================ field mapping

describe('field names the UI previously got wrong', () => {
  it('reads the FinOps savings field under its real name', async () => {
    vi.stubGlobal(
      'fetch',
      mockJson({
        waste_detected_count: 3,
        total_monthly_savings_usd: 440,
        waste_details: [{ resource_id: 'a' }, { resource_id: 'b' }, { resource_id: 'c' }],
      }),
    );

    const audit = await api.finops();

    // The old code read `monthly_savings_usd`, which does not exist, and fell
    // back to a hardcoded 440 — indistinguishable from the real value.
    expect(audit.total_monthly_savings_usd).toBe(440);
    expect(audit.waste_details).toHaveLength(3);
    expect((audit as unknown as Record<string, unknown>).monthly_savings_usd).toBeUndefined();
  });

  it('reads compiled skills under their real names', async () => {
    vi.stubGlobal(
      'fetch',
      mockJson({
        newly_compiled_count: 1,
        all_compiled_skills: [
          { skill_id: 's1', skeleton_signature: 'a->b', total_tokens_saved: 0, total_executions: 0 },
        ],
      }),
    );

    const { all_compiled_skills } = await api.mineSkills();

    // Previously read as `tokens_saved_per_run` and `execution_time_ms`, neither
    // of which the manifest has.
    expect(all_compiled_skills[0].total_tokens_saved).toBe(0);
    expect((all_compiled_skills[0] as unknown as Record<string, unknown>).tokens_saved_per_run).toBeUndefined();
  });

  it('unwraps the agent registry envelope', async () => {
    vi.stubGlobal('fetch', mockJson({ agents: [{ name: 'SyntruenoCommander' }] }));
    await expect(api.agents()).resolves.toHaveLength(1);
  });
});

// ================================================================== signing

describe('approval signing', () => {
  it('sends only the approval id and who is signing', async () => {
    const f = mockJson({ status: 'SUCCESS', approval_record: { approval_id: 'appr-1' } });
    vi.stubGlobal('fetch', f);

    await api.sign('appr-1', 'engineer@corp');

    const body = JSON.parse(f.mock.calls[0][1].body);
    expect(body).toEqual({ approval_id: 'appr-1', engineer_id: 'engineer@corp' });
    // The server reads the action from its own stored record. Sending one from
    // the client is what made the gate forgeable in the first place.
    expect(body).not.toHaveProperty('approval_record');
    expect(body).not.toHaveProperty('requested_action');
  });
});

// ============================================================ error surface

describe('errors surface instead of silently degrading', () => {
  it('raises ApiError carrying the server detail', async () => {
    vi.stubGlobal('fetch', mockJson({ detail: 'No pending approval' }, false, 404));
    await expect(api.sign('appr-forged', 'x')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      message: 'No pending approval',
    });
  });

  it('explains an unreachable backend rather than throwing a raw TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.status()).rejects.toBeInstanceOf(ApiError);
    await expect(api.status()).rejects.toThrow(/Cannot reach/);
  });
});

// ============================================================= sse parsing

describe('incident stream framing', () => {
  const collect = async (chunks: string[]) => {
    vi.stubGlobal('fetch', mockStream(chunks));
    const seen: StreamEvent[] = [];
    await streamIncident({} as never, (e) => seen.push(e));
    return seen;
  };

  it('parses whole frames', async () => {
    const seen = await collect([
      'data: {"type":"stage","stage":"armor","state":"done"}\n\n',
      'data: {"type":"done"}\n\n',
    ]);
    expect(seen.map((e) => e.type)).toEqual(['stage', 'done']);
  });

  it('reassembles a frame split across chunk boundaries', async () => {
    // The real failure mode: a network chunk ends mid-JSON. Parsing per chunk
    // would drop this event entirely.
    const seen = await collect([
      'data: {"type":"stage","stage":"dia',
      'gnose","state":"done","duration_ms":1178}\n\n',
    ]);
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ stage: 'diagnose', duration_ms: 1178 });
  });

  it('handles several frames arriving in one chunk', async () => {
    const seen = await collect([
      'data: {"type":"stage","stage":"recall","state":"active"}\n\n' +
        'data: {"type":"stage","stage":"recall","state":"done"}\n\n',
    ]);
    expect(seen).toHaveLength(2);
  });

  it('skips a malformed frame without tearing down the stream', async () => {
    const seen = await collect([
      'data: {"type":"stage","stage":"armor","state":"done"}\n\n',
      'data: {not json at all\n\n',
      'data: {"type":"done"}\n\n',
    ]);
    expect(seen.map((e) => e.type)).toEqual(['stage', 'done']);
  });

  it('ignores a trailing partial frame rather than emitting half an event', async () => {
    const seen = await collect([
      'data: {"type":"stage","stage":"judge","state":"done"}\n\n',
      'data: {"type":"sta',
    ]);
    expect(seen).toHaveLength(1);
  });
});
