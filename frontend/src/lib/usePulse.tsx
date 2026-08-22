/**
 * System pulse — a single coarse signal describing what the swarm is doing.
 *
 * The ambient field reads this to decide how to behave. Keeping it separate
 * from the incident state means the background layer never re-renders when a
 * stage detail changes; it only cares about the mood.
 */

import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

export type Pulse = 'idle' | 'thinking' | 'settled' | 'refused';

interface PulseApi {
  pulse: Pulse;
  /** Monotonic counter; bumping it fires one ripple through the field. */
  ripple: number;
  setPulse: (p: Pulse) => void;
  emitRipple: () => void;
}

const PulseContext = createContext<PulseApi>({
  pulse: 'idle',
  ripple: 0,
  setPulse: () => {},
  emitRipple: () => {},
});

export const usePulse = () => useContext(PulseContext);

export function PulseProvider({ children }: { children: ReactNode }) {
  const [pulse, setPulse] = useState<Pulse>('idle');
  const [ripple, setRipple] = useState(0);
  const count = useRef(0);

  const api = useMemo<PulseApi>(
    () => ({
      pulse,
      ripple,
      setPulse,
      emitRipple: () => setRipple(++count.current),
    }),
    [pulse, ripple],
  );

  return <PulseContext.Provider value={api}>{children}</PulseContext.Provider>;
}
