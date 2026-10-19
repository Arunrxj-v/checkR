import { useEffect } from "react";

import { Icon } from "./Icon";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}

export function Modal({ open, onClose, title, description, children, footer, width = "max-w-lg" }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center p-space-lg"
      style={{ background: "rgba(15, 42, 74, 0.4)" }}
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${width} animate-fade-in rounded-lg border border-outline-variant bg-surface-container-lowest shadow-modal`}
      >
        <div className="flex items-start justify-between gap-space-md border-b border-outline-variant px-space-lg py-space-md">
          <div>
            <h2 className=" text-headline-sm text-primary">{title}</h2>
            {description ? (
              <p className="mt-0.5  text-body-sm text-on-surface-variant">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded p-1 text-outline transition-colors hover:bg-surface-container-low hover:text-on-surface"
          >
            <Icon name="close" />
          </button>
        </div>
        {children ? <div className="px-space-lg py-space-md">{children}</div> : null}
        {footer ? (
          <div className="flex items-center justify-end gap-space-sm border-t border-outline-variant px-space-lg py-space-md">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}
