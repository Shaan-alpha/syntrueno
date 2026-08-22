/**
 * Application shell: header, navigation, theme, and the active view.
 *
 * This file used to be 811 lines holding every tab, all state, and every fetch
 * inline. Everything below is now navigation and chrome; the work lives in the
 * dashboard and panel components, and all network access goes through lib/api.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  DollarSign,
  Hammer,
  Moon,
  Network,
  ScrollText,
  ShieldCheck,
  Sun,
  type LucideIcon,
} from 'lucide-react';
import { Dashboard } from './components/dashboard/Dashboard';
import { SecurityStudio } from './components/panels/SecurityStudio';
import { CompilerPanel, FinOpsPanel, LedgerPanel, RegistryPanel } from './components/panels/InfraPanels';
import { ToastProvider } from './components/ui/Toast';
import { AmbientField } from './components/ui/AmbientField';
import { PulseProvider } from './lib/usePulse';
import { api } from './lib/api';

type ViewId = 'overview' | 'security' | 'compiler' | 'registry' | 'ledger' | 'spend';

const VIEWS: Array<{ id: ViewId; label: string; short: string; icon: LucideIcon }> = [
  { id: 'overview', label: 'Overview', short: 'Home', icon: Activity },
  { id: 'security', label: 'Security', short: 'Guard', icon: ShieldCheck },
  { id: 'compiler', label: 'ThorForja', short: 'Forge', icon: Hammer },
  { id: 'registry', label: 'Registry', short: 'Agents', icon: Network },
  { id: 'ledger', label: 'Ledger', short: 'Audit', icon: ScrollText },
  { id: 'spend', label: 'Spend', short: 'Cost', icon: DollarSign },
];

type Health = { reachable: boolean; llmLive: boolean };

function useHealth(): Health {
  const [health, setHealth] = useState<Health>({ reachable: false, llmLive: false });

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const h = await api.health();
        if (!cancelled) setHealth({ reachable: true, llmLive: Boolean(h.llm_available) });
      } catch {
        if (!cancelled) setHealth({ reachable: false, llmLive: false });
      }
    };
    void check();
    const id = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return health;
}

function useTheme() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    // ?theme=light forces a theme for screenshots and demos without having to
    // clear site data first.
    const forced = new URLSearchParams(window.location.search).get('theme');
    if (forced === 'light' || forced === 'dark') return forced;
    try {
      return (localStorage.getItem('syntrueno-theme') as 'dark' | 'light') ?? 'dark';
    } catch {
      return 'dark';
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('syntrueno-theme', theme);
    } catch {
      /* private browsing; the choice just will not persist */
    }
  }, [theme]);

  const toggle = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark';
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // The radial reveal is the one flourish worth keeping: it makes the switch
    // feel like the surface changing rather than the page reloading.
    const doc = document as Document & { startViewTransition?: (cb: () => void) => void };
    if (doc.startViewTransition && !reduced) {
      doc.startViewTransition(() => setTheme(next));
    } else {
      setTheme(next);
    }
  }, [theme]);

  return { theme, toggle };
}

function StatusPill({ health }: { health: Health }) {
  const tone = !health.reachable ? 'bad' : health.llmLive ? 'good' : 'warn';
  const label = !health.reachable
    ? 'Backend unreachable'
    : health.llmLive
      ? 'Gemini live'
      : 'Heuristic mode';

  return (
    <span className={`pill pill--${tone}`} title={
      health.llmLive
        ? 'Agents are calling Gemini'
        : health.reachable
          ? 'Reachable, but running offline heuristics'
          : 'The API is not responding'
    }>
      <span className="pill__dot" />
      {label}
    </span>
  );
}

export default function App() {
  const [view, setView] = useState<ViewId>('overview');
  const { theme, toggle } = useTheme();
  const health = useHealth();

  // Number keys jump between views. Cheap, and it makes the console feel like
  // a tool rather than a page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA)$/.test(target.tagName)) return;
      const index = Number(e.key) - 1;
      if (index >= 0 && index < VIEWS.length) setView(VIEWS[index].id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <PulseProvider>
      <ToastProvider>
        <AmbientField />
        <a className="skip" href="#main">Skip to content</a>

      <header className="topbar">
        <div className="topbar__brand">
          <span className="brand__mark" aria-hidden>S</span>
          <span className="brand__text">
            <strong>Syntrueno</strong>
            <span>Zero-trust cloud operations</span>
          </span>
        </div>

        <div className="topbar__right">
          <StatusPill health={health} />
          <button
            className="icon-btn"
            onClick={toggle}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          >
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      <nav className="nav" aria-label="Sections">
        {VIEWS.map((v, i) => {
          const Icon = v.icon;
          const active = view === v.id;
          return (
            <button
              key={v.id}
              className={`nav__item ${active ? 'nav__item--on' : ''}`}
              onClick={() => setView(v.id)}
              aria-current={active ? 'page' : undefined}
              title={`${v.label} — press ${i + 1}`}
            >
              <Icon size={16} strokeWidth={2.2} />
              <span className="nav__label">{v.label}</span>
              <span className="nav__label-short">{v.short}</span>
            </button>
          );
        })}
      </nav>

      <main id="main" className="main" key={view}>
        {view === 'overview' && <Dashboard />}
        {view === 'security' && <SecurityStudio />}
        {view === 'compiler' && <CompilerPanel />}
        {view === 'registry' && <RegistryPanel />}
        {view === 'ledger' && <LedgerPanel />}
        {view === 'spend' && <FinOpsPanel />}
      </main>

        <footer className="foot">
          <span>Syntrueno · Track 3 · Google Cloud All Things Agentic 2026</span>
          <span className="foot__dim">Every figure shown is measured, never assumed.</span>
        </footer>
      </ToastProvider>
    </PulseProvider>
  );
}
