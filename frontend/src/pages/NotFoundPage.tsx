import { Link } from "react-router-dom";

import { Icon } from "@/components/ui/Icon";

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-space-md bg-background px-margin text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded border border-outline-variant bg-surface-container-low">
        <Icon name="explore_off" className="text-[24px] text-outline" />
      </span>
      <div>
        <h1 className="font-display text-headline-lg font-semibold tracking-tight text-primary">
          Page not found
        </h1>
        <p className="mt-1  text-body-md text-on-surface-variant">
          The screen you are looking for does not exist or has moved.
        </p>
      </div>
      <Link to="/" className="btn-primary px-space-md py-1.5  text-label-md">
        <Icon name="home" className="text-[16px]" /> Back to dashboard
      </Link>
    </div>
  );
}
