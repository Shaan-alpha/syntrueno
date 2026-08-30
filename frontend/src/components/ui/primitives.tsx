/**
 * Small building blocks shared across the console.
 *
 * Kept deliberately plain: these carry behaviour that is easy to get wrong
 * (a button that stays disabled after an error, a metric that misaligns when
 * digits change) rather than styling, which lives in index.css.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';

/* ------------------------------------------------------------------ Card */

export function Card({
  title,
  subtitle,
  action,
  children,
  accent,
  className = '',
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  accent?: 'blue' | 'green' | 'yellow' | 'red' | 'purple';
  className?: string;
}) {
  return (
    <section className={`card ${accent ? `card--${accent}` : ''} ${className}`}>
      {(title || action) && (
        <header className="card__head">
          <div>
            {title && <h2 className="card__title">{title}</h2>}
            {subtitle && <p className="card__subtitle">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------- Button */

export function Button({
  children,
  onClick,
  variant = 'tonal',
  busy = false,
  disabled = false,
  icon,
  type = 'button',
  full = false,
}: {
  children: ReactNode;
  onClick?: () => void | Promise<void>;
  variant?: 'primary' | 'tonal' | 'ghost' | 'danger';
  busy?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  type?: 'button' | 'submit';
  full?: boolean;
}) {
  const ref = useRef<HTMLButtonElement>(null);

  // Ripple originates from the pointer, which is what makes a Material press
  // feel like it responded to *you* rather than playing a canned animation.
  const ripple = (e: React.MouseEvent<HTMLButtonElement>) => {
    const el = ref.current;
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const rect = el.getBoundingClientRect();
    const span = document.createElement('span');
    span.className = 'ripple';
    const size = Math.max(rect.width, rect.height);
    span.style.width = span.style.height = `${size}px`;
    span.style.left = `${e.clientX - rect.left - size / 2}px`;
    span.style.top = `${e.clientY - rect.top - size / 2}px`;
    el.appendChild(span);
    span.addEventListener('animationend', () => span.remove());
  };

  return (
    <button
      ref={ref}
      type={type}
      className={`btn btn--${variant} ${full ? 'btn--full' : ''}`}
      disabled={disabled || busy}
      aria-busy={busy}
      onClick={(e) => {
        ripple(e);
        void onClick?.();
      }}
    >
      {busy ? <span className="btn__spinner" aria-hidden /> : icon}
      <span>{children}</span>
    </button>
  );
}

/* ---------------------------------------------------------------- Metric */

export function Metric({
  label,
  value,
  unit,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: 'good' | 'warn' | 'bad' | 'muted';
  hint?: string;
}) {
  return (
    <div className="metric" title={hint}>
      <span className="metric__label">{label}</span>
      <span className={`metric__value ${tone ? `metric__value--${tone}` : ''}`}>
        {value}
        {unit && <span className="metric__unit">{unit}</span>}
      </span>
    </div>
  );
}

/** Counts up to a target. Used for the judge score, where the number landing
 *  is the moment worth drawing attention to. */
export function CountUp({ to, decimals = 1, duration = 500 }: { to: number; decimals?: number; duration?: number }) {
  // Resolved at mount instead of inside the effect. Reading it there meant the
  // reduced-motion path rendered 0, then set state to `to` on the very next
  // commit -- so the people who had asked not to be animated were the only ones
  // who saw the score move, 0.0 to 6.0, every time a verdict mounted. Now that
  // branch never animates and never sets state; it just renders the number.
  const [reduced] = useState(
    () => typeof window !== 'undefined'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  const [value, setValue] = useState(() => (reduced ? to : 0));

  useEffect(() => {
    if (reduced) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // ease-out cubic: fast arrival, gentle settle
      setValue(to * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, duration, reduced]);

  // `to` rather than `value` under reduced motion, so a later change to the
  // score still shows without the effect having to write it into state.
  return <>{(reduced ? to : value).toFixed(decimals)}</>;
}

/* ------------------------------------------------------------- StatusDot */

export function StatusDot({
  state,
  label,
}: {
  state: 'idle' | 'active' | 'done' | 'warn' | 'error';
  label?: string;
}) {
  return (
    <span className={`dot dot--${state}`} role="img" aria-label={label ?? state}>
      <span className="dot__core" />
      {state === 'active' && <span className="dot__ring" />}
    </span>
  );
}

/* -------------------------------------------------------------- Skeleton */

export function Skeleton({ lines = 3, width }: { lines?: number; width?: string }) {
  return (
    <div className="skeleton" aria-hidden style={width ? { width } : undefined}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton__line" style={{ width: `${100 - i * 12}%` }} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ EmptyState */

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      {icon && <div className="empty__icon">{icon}</div>}
      <p className="empty__title">{title}</p>
      {body && <p className="empty__body">{body}</p>}
      {action}
    </div>
  );
}

/* -------------------------------------------------------------- Progress */

/** Indeterminate bar plus a live elapsed counter.
 *
 *  The counter matters: a bare spinner during a 25-second model call reads as
 *  a hang. Showing time actually accumulating tells the user the system is
 *  working, without pretending to know how far along it is. */
export function LiveProgress({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setElapsed((performance.now() - since) / 1000), 100);
    return () => clearInterval(id);
  }, [since]);

  return (
    <div className="progress" role="progressbar" aria-label="Working">
      <div className="progress__bar" />
      <span className="progress__elapsed">{elapsed.toFixed(1)}s</span>
    </div>
  );
}

/* ------------------------------------------------------------------ Chip */

export function Chip({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'info';
}) {
  return <span className={`chip chip--${tone}`}>{children}</span>;
}
