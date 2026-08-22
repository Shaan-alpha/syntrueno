/**
 * The ambient field — this console's signature element.
 *
 * Not decoration. It is the fleet's pulse, and it reads as one:
 *
 *   idle       barely moving, cool indigo, low contrast. The system is calm.
 *   thinking   energises, hue shifts to cyan, links brighten. Reasoning.
 *   settled    a green wash relaxes back toward idle. Safety confirmed.
 *   refused    amber snap, motion arrests. Something was stopped.
 *
 * Every stage completion emits a ripple that propagates outward, so the
 * background is showing you the same events the timeline is listing.
 *
 * Performance is part of the design, not an afterthought:
 *   · one canvas, DPR capped at 1.5 — a retina screen does not need 4x here
 *   · frame budget drops to ~30fps when idle and rises to 60 only while active
 *   · rendering stops entirely when the tab is hidden
 *   · a single static frame under prefers-reduced-motion
 *   · node count scales with viewport, so phones do a third of the work
 */

import { useEffect, useRef } from 'react';
import { usePulse, type Pulse } from '../../lib/usePulse';

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
}

interface Ripple {
  born: number;
  hue: number;
}

/** Hue, saturation and energy per state. Hue is in degrees. */
const MOOD: Record<Pulse, { hue: number; energy: number; link: number }> = {
  // Idle still has to be *present* — it is the resting state of a system that
  // is watching, not a system that is off.
  idle: { hue: 244, energy: 0.28, link: 0.5 },
  thinking: { hue: 196, energy: 1.1, link: 1.0 },
  settled: { hue: 142, energy: 0.4, link: 0.66 },
  refused: { hue: 30, energy: 0.12, link: 0.8 },
};

const LINK_DISTANCE = 205;

export function AmbientField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { pulse, ripple } = usePulse();

  // Kept in refs so a state change never restarts the animation loop.
  const moodRef = useRef(MOOD.idle);
  const ripplesRef = useRef<Ripple[]>([]);
  const lastRipple = useRef(0);

  useEffect(() => {
    moodRef.current = MOOD[pulse];
  }, [pulse]);

  useEffect(() => {
    if (ripple === lastRipple.current) return;
    lastRipple.current = ripple;
    ripplesRef.current.push({ born: performance.now(), hue: MOOD[pulse].hue });
  }, [ripple, pulse]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let nodes: Node[] = [];
    let width = 0;
    let height = 0;
    let dpr = 1;
    let raf = 0;
    let lastFrame = 0;
    // Eased so the hue glides between moods instead of cutting.
    let hue = MOOD.idle.hue;
    let energy = MOOD.idle.energy;
    let link = MOOD.idle.link;

    const seed = () => {
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Density by area, so a phone renders roughly a third of a desktop.
      const target = Math.round(Math.min(110, Math.max(34, (width * height) / 13500)));
      nodes = Array.from({ length: target }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: 0.7 + Math.random() * 1.5,
      }));
    };

    const draw = (now: number) => {
      const mood = moodRef.current;

      // Glide toward the target mood. Slow enough to feel like a system
      // settling rather than a colour swap.
      hue += ((mood.hue - hue) * 0.02);
      energy += (mood.energy - energy) * 0.03;
      link += (mood.link - link) * 0.03;

      ctx.clearRect(0, 0, width, height);

      // Links first, so nodes sit on top of their own connections.
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > LINK_DISTANCE * LINK_DISTANCE) continue;
          const closeness = 1 - Math.sqrt(d2) / LINK_DISTANCE;
          ctx.strokeStyle = `hsla(${hue}, 92%, 72%, ${closeness * link * 0.3})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      for (const n of nodes) {
        ctx.fillStyle = `hsla(${hue}, 95%, 78%, ${0.34 + link * 0.34})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();

        n.x += n.vx * (0.35 + energy);
        n.y += n.vy * (0.35 + energy);

        // Wrap rather than bounce: a bounce reads as a wall, and there is no
        // wall in the thing this represents.
        if (n.x < -20) n.x = width + 20;
        if (n.x > width + 20) n.x = -20;
        if (n.y < -20) n.y = height + 20;
        if (n.y > height + 20) n.y = -20;
      }

      // Ripples: one expanding ring per completed stage.
      ripplesRef.current = ripplesRef.current.filter((r) => {
        const age = (now - r.born) / 1700;
        if (age >= 1) return false;
        const radius = age * Math.max(width, height) * 0.62;
        ctx.strokeStyle = `hsla(${r.hue}, 92%, 70%, ${(1 - age) * 0.2})`;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(width / 2, height * 0.42, radius, 0, Math.PI * 2);
        ctx.stroke();
        return true;
      });
    };

    const loop = (now: number) => {
      // 60fps while there is something to say, ~30fps at rest.
      const budget = moodRef.current.energy > 0.4 || ripplesRef.current.length ? 16 : 33;
      if (now - lastFrame >= budget) {
        lastFrame = now;
        draw(now);
      }
      raf = requestAnimationFrame(loop);
    };

    const start = () => {
      cancelAnimationFrame(raf);
      if (reduced.matches) {
        draw(performance.now());
        return;
      }
      raf = requestAnimationFrame(loop);
    };

    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else start();
    };

    let resizeTimer = 0;
    const onResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        seed();
        if (reduced.matches) draw(performance.now());
      }, 160);
    };

    seed();
    start();
    window.addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibility);
    reduced.addEventListener('change', start);

    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(resizeTimer);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibility);
      reduced.removeEventListener('change', start);
    };
  }, []);

  return (
    <div className="ambient" aria-hidden="true">
      {/* Two slow aurora washes behind the mesh. Pure CSS transforms, so the
          compositor handles them and the main thread stays free. */}
      <span className="ambient__aurora ambient__aurora--a" />
      <span className="ambient__aurora ambient__aurora--b" />
      <canvas ref={canvasRef} className="ambient__mesh" />
      <span className="ambient__vignette" />
    </div>
  );
}
