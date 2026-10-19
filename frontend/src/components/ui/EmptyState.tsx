import { Icon } from "./Icon";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon = "inbox", title, description, action, className = "" }: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-space-sm rounded-lg border border-dashed border-outline-variant bg-surface-container-lowest px-space-xl py-14 text-center ${className}`}
    >
      <Icon name={icon} className="text-[28px] text-outline" />
      <div className="max-w-md">
        <h3 className=" text-headline-sm text-primary">{title}</h3>
        {description ? (
          <p className="mt-1  text-body-sm text-on-surface-variant">{description}</p>
        ) : null}
      </div>
      {action ? <div className="mt-space-xs">{action}</div> : null}
    </div>
  );
}
