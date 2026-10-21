import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Icon } from "@/components/ui/Icon";
import { apiRequest } from "@/lib/api";
import { initials } from "@/lib/format";
import type { AppSettings, Page, Submission, User } from "@/lib/types";

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

function NavRow({
  item,
  badge,
  onNavigate,
}: {
  item: NavItem;
  badge?: number;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        `flex min-h-[2.25rem] items-center justify-between rounded px-space-sm py-1.5 text-body-sm transition-colors ${
          isActive
            ? "bg-desk-high font-medium text-desk-text"
            : "text-desk-muted hover:bg-desk-raised hover:text-desk-text"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span className="flex min-w-0 items-center gap-space-sm">
            <Icon name={item.icon} filled={isActive} className="text-[18px]" />
            <span className="truncate">{item.label}</span>
          </span>
          {badge ? (
            <span
              className={`ml-2 rounded px-1.5 py-0.5 font-mono text-[10px] font-medium ${
                isActive ? "bg-primary-fixed-dim text-on-primary-fixed" : "bg-desk-high text-desk-text"
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

function Brand() {
  return (
    <Link to="/" className="inline-flex min-w-0 flex-col gap-0.5">
      <span className="font-reading text-[24px] font-semibold leading-none tracking-tight text-desk-text">
        check<span className="text-primary-fixed-dim">R</span>
      </span>
      <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-desk-muted">
        Examination desk
      </span>
    </Link>
  );
}

function SidebarContent({
  user,
  settings,
  pendingReview,
  onNavigate,
  onSignOut,
}: {
  user: User | null | undefined;
  settings: AppSettings | null;
  pendingReview: number | null;
  onNavigate?: () => void;
  onSignOut: () => void;
}) {
  const navigate = useNavigate();
  const [accountOpen, setAccountOpen] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col justify-between">
      <div className="flex min-h-0 flex-col">
        <div className="flex h-16 shrink-0 items-center border-b border-desk-line px-gutter">
          <Brand />
        </div>
        <div className="p-space-md">
          <div className="px-space-sm pb-space-xs font-mono text-[9px] font-medium uppercase tracking-[0.16em] text-desk-muted">
            Evaluation hub
          </div>
          <nav className="flex flex-col gap-0.5" aria-label="Main navigation">
            {NAV_ITEMS.map((item) => (
              <NavRow
                key={item.to}
                item={item}
                badge={item.to === "/evaluation" ? (pendingReview ?? undefined) : undefined}
                onNavigate={onNavigate}
              />
            ))}
          </nav>
        </div>
      </div>

      <div className="border-t border-desk-line">
        <div className="relative flex flex-col gap-space-xs px-gutter py-space-md">
          <button
            type="button"
            onClick={() => setAccountOpen((v) => !v)}
            aria-expanded={accountOpen}
            className="flex min-h-[2.5rem] items-start justify-between gap-space-xs rounded text-left"
          >
            <div className="min-w-0">
              <div className="truncate text-body-sm font-medium text-desk-text">
                {user?.full_name ?? "Signed in"}
              </div>
              <div className="truncate text-label-sm text-desk-muted">
                {user?.department ?? user?.institution ?? user?.email ?? ""}
              </div>
            </div>
            <span className="inline-flex shrink-0 items-center rounded border border-desk-line px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em] text-desk-muted">
              {user?.role ?? "teacher"}
            </span>
          </button>
          <div className="flex items-center justify-between font-mono text-[10px] text-desk-muted">
            <span className="truncate">
              {settings
                ? settings.environment === "production"
                  ? "Production environment"
                  : `${settings.environment} environment`
                : "Session active"}
            </span>
            <button
              type="button"
              onClick={onSignOut}
              className="rounded px-1 py-0.5 text-desk-muted transition-colors hover:bg-desk-raised hover:text-desk-text"
            >
              Sign out
            </button>
          </div>
          {accountOpen ? (
            <div className="absolute bottom-full left-gutter right-gutter mb-2 overflow-hidden rounded border border-desk-line bg-desk-raised shadow-menu">
              <button
                type="button"
                onClick={() => {
                  setAccountOpen(false);
                  onNavigate?.();
                  navigate("/settings");
                }}
                className="flex min-h-[2.25rem] w-full items-center gap-space-sm px-space-sm py-2 text-left text-body-sm text-desk-text hover:bg-desk-high"
              >
                <Icon name="manage_accounts" className="text-[16px]" /> Account settings
              </button>
              <button
                type="button"
                onClick={onSignOut}
                className="flex min-h-[2.25rem] w-full items-center gap-space-sm border-t border-desk-line px-space-sm py-2 text-left text-body-sm text-critical-border hover:bg-desk-high"
              >
                <Icon name="logout" className="text-[16px]" /> Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [pendingReview, setPendingReview] = useState<number | null>(null);
  const [navOpen, setNavOpen] = useState(false);

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

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!navOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", close);
    };
  }, [navOpen]);

  const ctx = useMemo<ShellContextValue>(() => ({ setCrumbs }), []);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <ShellContext.Provider value={ctx}>
      <div className="on-desk min-h-[100dvh] bg-background">
        <aside className="fixed inset-y-0 left-0 z-50 hidden w-64 flex-col bg-desk lg:flex">
          <SidebarContent
            user={user}
            settings={settings}
            pendingReview={pendingReview}
            onSignOut={handleLogout}
          />
        </aside>

        {navOpen ? (
          <div className="fixed inset-0 z-50 lg:hidden">
            <button
              type="button"
              aria-label="Close navigation"
              className="absolute inset-0 bg-desk/70"
              onClick={() => setNavOpen(false)}
            />
            <aside
              id="mobile-navigation"
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              className="relative flex h-full w-[min(18rem,calc(100vw-3rem))] flex-col bg-desk shadow-modal"
            >
              <SidebarContent
                user={user}
                settings={settings}
                pendingReview={pendingReview}
                onNavigate={() => setNavOpen(false)}
                onSignOut={handleLogout}
              />
            </aside>
          </div>
        ) : null}

        <div className="lg:pl-64">
          <header className="sticky top-0 z-40 flex h-14 items-center justify-between gap-space-sm border-b border-desk-line bg-desk px-gutter">
            <div className="flex min-w-0 items-center gap-space-sm">
              <button
                type="button"
                aria-label="Open navigation"
                aria-expanded={navOpen}
                aria-controls="mobile-navigation"
                onClick={() => setNavOpen(true)}
                className="rounded p-1.5 text-desk-muted transition-colors hover:bg-desk-raised hover:text-desk-text lg:hidden"
              >
                <Icon name="menu" className="text-[22px]" />
              </button>
              <span className="font-reading text-[20px] font-semibold leading-none text-desk-text lg:hidden">
                check<span className="text-primary-fixed-dim">R</span>
              </span>
              <div className="hidden min-w-0 items-center gap-space-xs text-body-sm text-desk-muted lg:flex">
                {crumbs.length === 0 ? (
                  <span className="truncate text-desk-text">Examination operations</span>
                ) : (
                  crumbs.map((crumb, index) => {
                    const last = index === crumbs.length - 1;
                    return (
                      <span
                        key={`${crumb.label}-${index}`}
                        className="flex min-w-0 items-center gap-space-xs"
                      >
                        {index > 0 ? <span className="shrink-0 text-desk-line">/</span> : null}
                        {crumb.to && !last ? (
                          <Link
                            to={crumb.to}
                            className="shrink-0 rounded transition-colors hover:text-desk-text"
                          >
                            {crumb.label}
                          </Link>
                        ) : (
                          <span
                            className={
                              last ? "truncate font-medium text-desk-text" : "shrink-0"
                            }
                          >
                            {crumb.label}
                          </span>
                        )}
                      </span>
                    );
                  })
                )}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-space-sm">
              {settings ? (
                <span
                  className={`hidden items-center gap-space-xs rounded border px-space-sm py-1 font-mono text-[10px] uppercase tracking-[0.08em] sm:flex ${
                    settings.ai.is_mock
                      ? "border-review/50 bg-desk-raised text-review-border"
                      : "border-desk-line bg-desk-raised text-desk-muted"
                  }`}
                  title={
                    settings.ai.is_mock
                      ? "Deterministic mock provider — results are reproducible and clearly marked."
                      : `Live provider: ${settings.ai.provider}`
                  }
                >
                  <Icon name={settings.ai.is_mock ? "science" : "verified"} className="text-[14px]" />
                  {settings.ai.is_mock ? "Mock AI" : "Live AI"}
                  <span className="hidden text-desk-muted md:inline">{settings.ai.provider}</span>
                </span>
              ) : null}
              <Link
                to="/evaluation"
                aria-label={
                  pendingReview
                    ? `${pendingReview} scripts ready for review`
                    : "Open the evaluation queue"
                }
                title={pendingReview ? `${pendingReview} scripts ready for review` : "Evaluation queue"}
                className="relative flex h-8 w-8 items-center justify-center rounded text-desk-muted transition-colors hover:bg-desk-raised hover:text-desk-text"
              >
                <Icon name="fact_check" className="text-[20px]" />
                {pendingReview ? (
                  <span className="absolute -right-1 -top-1 min-w-[16px] rounded border border-review-border bg-review-bg px-1 text-center font-mono text-[9px] font-semibold leading-4 text-review-fg">
                    {pendingReview > 99 ? "99+" : pendingReview}
                  </span>
                ) : null}
              </Link>
              <Link
                to="/settings"
                aria-label="Account settings"
                title={user?.email}
                className="flex h-8 w-8 items-center justify-center rounded border border-desk-line bg-desk-raised font-mono text-[11px] font-semibold text-desk-text transition-colors hover:border-desk-muted"
              >
                {initials(user?.full_name)}
              </Link>
            </div>
          </header>

          <main className="min-h-[calc(100dvh-3.5rem)] w-full bg-background">
            <Outlet />
          </main>
        </div>
      </div>
    </ShellContext.Provider>
  );
}

export function MockModeBanner({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-start gap-space-sm border-b border-review-border bg-review-bg px-space-md py-2 text-body-sm text-review-fg">
      <Icon name="science" className="mt-0.5 text-[16px]" />
      <span>
        <strong className="font-semibold">Mock AI mode.</strong> The provider is deterministic and produces
        reproducible marks for demonstration. {children}
      </span>
    </div>
  );
}
