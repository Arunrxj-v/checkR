import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { TONE_BADGE, type Tone } from "@/lib/status";

import { Icon } from "./Icon";

interface Toast {
  id: number;
  message: string;
  tone: Tone;
  detail?: string;
}

interface ToastContextValue {
  notify: (message: string, options?: { tone?: Tone; detail?: string }) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const ICONS: Record<Tone, string> = {
  verified: "check_circle",
  review: "error",
  critical: "report",
  neutral: "info",
  info: "info",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback<ToastContextValue["notify"]>((message, options) => {
    const id = Date.now() + Math.random();
    const tone = options?.tone ?? "neutral";
    setToasts((prev) => [...prev, { id, message, tone, detail: options?.detail }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, tone === "critical" ? 7000 : 4200);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={`pointer-events-auto animate-fade-in rounded-lg border bg-surface-container-lowest p-space-md shadow-modal`}
          >
            <div className="flex items-start gap-space-sm">
              <span className={`mt-0.5 rounded border p-0.5 ${TONE_BADGE[toast.tone]}`}>
                <Icon name={ICONS[toast.tone]} className="text-[16px]" />
              </span>
              <div className="min-w-0 flex-1">
                <p className=" text-body-sm font-medium text-on-surface">{toast.message}</p>
                {toast.detail ? (
                  <p className="mt-0.5 break-words  text-body-sm text-on-surface-variant">
                    {toast.detail}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
                className="text-outline transition-colors hover:text-on-surface"
              >
                <Icon name="close" className="text-[16px]" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
