import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Icon } from "@/components/ui/Icon";
import { apiRequest } from "@/lib/api";
import { initials } from "@/lib/format";
import type { AppSettings, Page, Submission } from "@/lib/types";

export interface Crumb {
  label: string;
  to?: string;
}

interface ShellContextValue {
  setCrumbs: (crumbs: Crumb[]) => void;
}

const ShellContext = createContext<ShellContextValue>({ setCrumbs: () => undefined });

/** Pages declare the breadcrumb trail shown in the global header. */
export function useCrumbs(crumbs: Crumb[], deps: unknown[] = []) {
  const { setCrumbs } = useContext(ShellContext);
  const key = JSON.stringify(crumbs);
  useEffect(() => {
    setCrumbs(crumbs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ...deps]);
}

interface NavItem {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/exams", label: "Examinations", icon: "menu_book" },
  { to: "/answer-sheets", label: "Answer Sheets", icon: "description" },
  { to: "/evaluation", label: "Evaluation", icon: "check_box" },
  { to: "/results", label: "Results", icon: "bar_chart" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

function NavRow({ item, badge }: { item: NavItem; badge?: number }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        `flex items-center justify-between rounded px-space-sm py-1.5  text-body-md transition-colors ${
          isActive
            ? "bg-primary-container font-medium text-on-primary"
            : "text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span className="flex items-center gap-space-sm">
            <Icon name={item.icon} filled={isActive} />
            <span>{item.label}</span>
          </span>
          {badge ? (
            <span
              className={`rounded px-1.5 py-0.5  text-label-sm ${
                isActive
                  ? "bg-review-bg text-review-fg"
                  : "bg-surface-container text-on-surface-variant"
              }`}
            >
              {badge}
            </span>
          ) : null}
        </>
      )}
    </NavLink>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [pendingReview, setPendingReview] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiRequest<AppSettings>("/settings")
      .then((s) => !cancelled && setSettings(s))
      .catch(() => undefined);
    apiRequest<Page<Submission>>("/submissions", { query: { status: "ready_for_review", limit: 1 } })
      .then((page) => !cancelled && setPendingReview(page.total))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const ctx = useMemo<ShellContextValue>(() => ({ setCrumbs }), []);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <ShellContext.Provider value={ctx}>
      <aside className="fixed left-0 top-0 z-50 flex h-screen w-64 select-none flex-col justify-between border-r border-outline-variant bg-surface-container-lowest">
        <div className="flex flex-col">
          <div className="flex h-14 items-center justify-between border-b border-outline-variant px-gutter">
            <div className="flex items-center gap-space-sm">
              <span className="font-display text-headline-sm font-semibold tracking-tight text-primary">
                check<span className="text-secondary">R</span>
              </span>
              <span className="rounded border border-outline-variant bg-surface-container px-space-xs py-0.5  text-label-sm font-medium text-on-surface-variant">
                Academic v2.4
              </span>
            </div>
          </div>
          <div className="p-space-md">
            <div className="px-space-sm pb-space-xs  text-label-sm font-semibold uppercase tracking-wider text-outline">
              Evaluation Hub
            </div>
            <nav className="flex flex-col gap-0.5">
              {NAV_ITEMS.map((item) => (
                <NavRow
                  key={item.to}
                  item={item}
                  badge={item.to === "/evaluation" ? (pendingReview ?? undefined) : undefined}
                />
              ))}
            </nav>
          </div>
        </div>

        <div className="flex flex-col border-t border-outline-variant bg-surface-container-lowest">
          <div className="border-b border-outline-variant bg-surface-container-low px-gutter py-space-sm">
            <div className="flex items-center justify-between text-on-surface-variant">
              <span className=" text-label-sm font-medium text-outline">ACTIVE SESSION</span>
              <span className="h-1.5 w-1.5 rounded-full bg-verified" aria-hidden />
            </div>
            <div className="mt-0.5  text-body-sm font-medium text-on-surface">
              {settings?.environment === "production" ? "Production" : "Fall 2026 · Midterm"}
            </div>
          </div>
          <div className="relative flex flex-col gap-space-xs px-gutter py-space-md">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-start justify-between gap-space-xs text-left"
            >
              <div className="min-w-0">
                <div className="truncate  text-body-sm font-semibold text-on-surface">
                  {user?.full_name ?? "Signed in"}
                </div>
                <div className="truncate  text-label-sm text-on-surface-variant">
                  {user?.department ?? user?.institution ?? user?.email ?? ""}
                </div>
              </div>
              <span className="inline-flex items-center rounded border border-verified-border bg-verified-bg px-1.5 py-0.5 text-[10px] font-medium capitalize text-verified-fg">
                {user?.role ?? "teacher"}
              </span>
            </button>
            {menuOpen ? (
              <div className="absolute bottom-full left-gutter right-gutter mb-1 overflow-hidden rounded border border-outline-variant bg-surface-container-lowest shadow-menu">
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate("/settings");
                  }}
                  className="flex w-full items-center gap-space-sm px-space-sm py-2 text-left  text-body-sm text-on-surface-variant hover:bg-surface-container-low"
                >
                  <Icon name="manage_accounts" className="text-[16px]" /> Account settings
                </button>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex w-full items-center gap-space-sm border-t border-outline-variant px-space-sm py-2 text-left  text-body-sm text-critical-fg hover:bg-critical-bg"
                >
                  <Icon name="logout" className="text-[16px]" /> Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </aside>

      <div className="pl-64">
        <header className="fixed left-64 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-outline-variant bg-surface-container-lowest/90 px-gutter backdrop-blur-md">
          <div className="flex min-w-0 items-center gap-space-xs  text-body-sm text-on-surface-variant">
            <span className="shrink-0">checkR</span>
            {crumbs.map((crumb, index) => (
              <span key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-space-xs">
                <span className="shrink-0 text-outline">/</span>
                <span
                  className={
                    index === crumbs.length - 1
                      ? "truncate font-medium text-on-surface"
                      : "shrink-0"
                  }
                >
                  {crumb.label}
                </span>
              </span>
            ))}
          </div>
          <div className="flex shrink-0 items-center gap-space-md">
            {settings ? (
              <>
                <span
                  className={`hidden items-center gap-space-xs rounded border px-space-sm py-1  text-label-md sm:flex ${
                    settings.ai.is_mock
                      ? "border-review-border bg-review-bg text-review-fg"
                      : "border-outline-variant bg-surface-container-low text-on-surface-variant"
                  }`}
                  title={
                    settings.ai.is_mock
                      ? "Deterministic mock provider — results are reproducible and clearly marked."
                      : `Live provider: ${settings.ai.provider}`
                  }
                >
                  <span
                    className={`h-2 w-2 rounded-full ${settings.ai.is_mock ? "bg-review" : "bg-verified"}`}
                    aria-hidden
                  />
                  {settings.ai.is_mock ? "Mock AI" : "Live AI"}
                  <span className=" text-[10px] text-outline">{settings.ai.provider}</span>
                </span>
                <div className="hidden h-4 w-px bg-outline-variant sm:block" />
              </>
            ) : null}
            <span className="flex items-center gap-space-xs  text-label-md text-on-surface-variant">
              <span className="h-2 w-2 rounded-full bg-verified" aria-hidden />
              <span className="hidden lg:inline">System Live</span>
            </span>
            <button
              type="button"
              aria-label="Notifications"
              onClick={() => navigate("/evaluation")}
              className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container-low hover:text-on-surface"
            >
              <Icon name="notifications" className="text-[20px]" />
            </button>
            <span
              className="flex h-8 w-8 items-center justify-center rounded-full border border-outline-variant bg-surface-container  text-label-sm font-semibold text-primary"
              title={user?.email}
            >
              {initials(user?.full_name)}
            </span>
          </div>
        </header>

        <main className="min-h-screen w-full bg-background pt-14">
          <Outlet />
        </main>
      </div>
    </ShellContext.Provider>
  );
}

export function MockModeBanner({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-center gap-space-sm border-b border-review-border bg-review-bg px-space-md py-1.5  text-body-sm text-review-fg">
      <Icon name="science" className="text-[16px]" />
      <span>
        <strong className="font-semibold">Mock AI mode.</strong> The provider is deterministic and produces
        reproducible marks for demonstration. {children}
      </span>
    </div>
  );
}
