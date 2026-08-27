/**
 * Toast notifications.
 *
 * Exists because actions used to complete silently: you clicked Approve, the
 * request either worked or 404'd, and the console looked identical either way.
 * Every outcome now says what happened — including the failures, which is the
 * half that was missing.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ToastTone = 'success' | 'error' | 'info' | 'warn';

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
}

interface ToastApi {
  show: (tone: ToastTone, title: string, body?: string) => void;
  success: (title: string, body?: string) => void;
  error: (title: string, body?: string) => void;
  info: (title: string, body?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (tone: ToastTone, title: string, body?: string) => {
      const id = nextId.current++;
      setToasts((prev) => [...prev.slice(-3), { id, tone, title, body }]);
      // Errors linger: they usually need reading, and often acting on.
      const ttl = tone === 'error' ? 8000 : 4000;
      setTimeout(() => dismiss(id), ttl);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (t, b) => show('success', t, b),
      error: (t, b) => show('error', t, b),
      info: (t, b) => show('info', t, b),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="region" aria-label="Notifications">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const [leaving, setLeaving] = useState(false);

  // Errors announce assertively; everything else waits its turn, because a
  // success toast interrupting a screen reader mid-sentence is worse than it
  // arriving a moment later. That lives on the aria-live attribute below --
  // an empty useEffect used to sit here carrying only this comment.
  return (
    <div
      className={`toast toast--${toast.tone} ${leaving ? 'toast--leaving' : ''}`}
      role={toast.tone === 'error' ? 'alert' : 'status'}
      aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}
    >
      <div className="toast__body">
        <p className="toast__title">{toast.title}</p>
        {toast.body && <p className="toast__detail">{toast.body}</p>}
      </div>
      <button
        className="toast__close"
        aria-label="Dismiss notification"
        onClick={() => {
          setLeaving(true);
          setTimeout(onDismiss, 180);
        }}
      >
        ×
      </button>
    </div>
  );
}
