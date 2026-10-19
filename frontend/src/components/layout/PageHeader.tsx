interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}

/** Calm section header used at the top of every non-workspace screen. */
export function PageHeader({ title, description, actions, children }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-space-md border-b border-outline-variant pb-space-md sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-display text-headline-lg font-semibold tracking-tight text-primary">{title}</h1>
        {description ? (
          <p className="mt-0.5  text-body-md text-on-surface-variant">{description}</p>
        ) : null}
        {children}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-space-sm">{actions}</div> : null}
    </div>
  );
}

export function PageContainer({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`mx-auto flex w-full max-w-[1520px] flex-col gap-space-lg px-gutter py-space-lg lg:px-margin ${className}`}>
      {children}
    </div>
  );
}
