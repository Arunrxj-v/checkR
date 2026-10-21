import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Icon } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, authApi } from "@/lib/api";
import { resolveLoginExperience, type AuthMode } from "@/lib/authOptions";

export function LoginPage() {
  const { login, register, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [requestedMode, setRequestedMode] = useState<AuthMode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [department, setDepartment] = useState("");
  const [institution, setInstitution] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Public endpoint: whether account creation is offered and — in development
  // only — which demo account is seeded. Production always returns null, so
  // there is no demo credential anywhere in this bundle.
  const environmentQuery = useQuery({
    queryKey: ["auth-environment"],
    queryFn: ({ signal }) => authApi.environment(signal),
    staleTime: Infinity,
    retry: false,
  });

  const { mode, registrationEnabled, demoCredentials } = resolveLoginExperience(
    environmentQuery.data,
    requestedMode,
  );

  const redirectTo = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "authenticated") {
    return <Navigate to={redirectTo} replace />;
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") {
        await login(email.trim(), password);
      } else {
        await register({
          email: email.trim(),
          full_name: fullName.trim(),
          password,
          department: department.trim() || undefined,
          institution: institution.trim() || undefined,
        });
      }
      navigate(redirectTo, { replace: true });
    } catch (err) {
      // The API returns the same message for an unknown address and a wrong
      // password, so the form never reveals whether an account exists.
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const useDemoCredentials = () => {
    if (!demoCredentials) return;
    setEmail(demoCredentials.email);
    setPassword(demoCredentials.password);
    setError(null);
  };

  return (
    <div className="on-desk flex min-h-[100dvh] items-center justify-center bg-desk px-3 py-5 sm:px-6 sm:py-8 lg:px-10">
      <div className="w-full max-w-[1040px] overflow-hidden rounded border border-desk-line bg-surface-container-lowest shadow-paper">
        <header className="flex flex-wrap items-center justify-between gap-space-sm border-b border-outline-variant px-5 py-4 sm:px-8">
          <div className="flex items-center gap-space-sm">
            <span className="font-reading text-[26px] font-semibold leading-none tracking-tight text-primary">
              check<span className="text-secondary">R</span>
            </span>
            <span className="h-4 w-px bg-outline-variant" aria-hidden />
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-outline">
              Examiner access
            </span>
          </div>
          <span className="flex items-center gap-space-xs font-mono text-[10px] uppercase tracking-[0.1em] text-outline">
            <Icon name="lock" className="text-[14px]" />
            Human decision required
          </span>
        </header>

        <div className="grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
          <main className="px-5 py-7 sm:px-8 sm:py-10 lg:px-10">
            <div className="max-w-sm">
              <div className="label-overline">Secure sign in</div>
              <h1 className="mt-2 font-reading text-[34px] font-medium leading-[1.1] tracking-tight text-primary">
                {mode === "signin" ? "Take your seat at the desk." : "Register as an examiner."}
              </h1>
              <p className="mt-3 text-body-md text-on-surface-variant">
                {mode === "signin"
                  ? "Use your institutional credentials to open the evaluation desk."
                  : "Create an account to set examinations and review answer scripts."}
              </p>

              <form onSubmit={submit} className="mt-7 flex flex-col gap-space-md">
                {error ? (
                  <p
                    role="alert"
                    className="flex items-start gap-space-sm rounded border border-error/40 bg-error-container px-space-md py-space-sm text-body-sm text-on-error-container"
                  >
                    <Icon name="error" className="mt-px text-[16px]" />
                    <span>{error}</span>
                  </p>
                ) : null}

                {mode === "register" ? (
                  <Field label="Full name" htmlFor="full_name">
                    <input
                      id="full_name"
                      className="field"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      required
                      autoComplete="name"
                      placeholder="Dr. Evelyn Reed"
                    />
                  </Field>
                ) : null}

                <Field label="Email" htmlFor="email">
                  <input
                    id="email"
                    type="email"
                    className="field font-mono"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="username"
                    placeholder="you@institution.edu"
                  />
                </Field>

                <Field label="Password" htmlFor="password">
                  <input
                    id="password"
                    type="password"
                    className="field"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={mode === "register" ? 8 : undefined}
                    autoComplete={mode === "signin" ? "current-password" : "new-password"}
                    placeholder="••••••••"
                  />
                </Field>

                {mode === "register" ? (
                  <div className="grid gap-space-md sm:grid-cols-2">
                    <Field label="Department" htmlFor="department">
                      <input
                        id="department"
                        className="field"
                        value={department}
                        onChange={(e) => setDepartment(e.target.value)}
                        placeholder="Computer Science"
                      />
                    </Field>
                    <Field label="Institution" htmlFor="institution">
                      <input
                        id="institution"
                        className="field"
                        value={institution}
                        onChange={(e) => setInstitution(e.target.value)}
                        placeholder="State University"
                      />
                    </Field>
                  </div>
                ) : null}

                <button
                  type="submit"
                  disabled={busy}
                  aria-busy={busy}
                  className="btn-primary mt-space-xs h-11 text-label-md"
                >
                  {busy ? <Spinner className="h-4 w-4 border-white/40 border-t-white" /> : null}
                  {mode === "signin" ? "Sign in to the desk" : "Create examiner account"}
                </button>
              </form>

              {registrationEnabled || demoCredentials ? (
                <div className="mt-space-lg flex flex-wrap items-center justify-between gap-space-sm border-t border-outline-variant pt-space-md">
                  {registrationEnabled ? (
                    <button
                      type="button"
                      className="text-label-md text-secondary hover:underline"
                      onClick={() => {
                        setRequestedMode(mode === "signin" ? "register" : "signin");
                        setError(null);
                      }}
                    >
                      {mode === "signin" ? "Create an account" : "I already have an account"}
                    </button>
                  ) : null}

                  {demoCredentials ? (
                    <button
                      type="button"
                      className="ml-auto text-label-sm text-outline hover:text-on-surface"
                      onClick={useDemoCredentials}
                    >
                      Use demo credentials
                    </button>
                  ) : null}
                </div>
              ) : null}

              {demoCredentials ? (
                <p className="mt-space-md rounded border border-outline-variant bg-surface-container-low px-space-md py-space-sm text-body-sm text-on-surface-variant">
                  <Icon name="info" className="mr-1 text-[14px] align-[-2px]" />
                  Development seed account —{" "}
                  <span className="font-mono">{demoCredentials.email}</span> /{" "}
                  <span className="font-mono">{demoCredentials.password}</span>
                </p>
              ) : null}
            </div>
          </main>

          <aside className="border-t border-outline-variant bg-surface-container-low px-5 py-7 sm:px-8 sm:py-10 lg:border-l lg:border-t-0 lg:px-9">
            <div className="label-overline">The examiner's desk</div>
            <h2 className="mt-2 max-w-[24ch] font-reading text-[30px] font-medium leading-[1.15] tracking-tight text-primary">
              Every mark leaves a trail.
            </h2>
            <p className="mt-4 font-reading text-reading-md text-on-surface-variant">
              CheckR reads the manuscript and proposes criteria-level marks. The decision stays with the
              examiner, and the record shows exactly how it was reached.
            </p>

            <ol className="mt-7 space-y-4 border-t border-outline-variant pt-5">
              {[
                ["01", "Answers are matched to the question they belong to."],
                ["02", "Marks are proposed against your marking scheme."],
                ["03", "Your decision and the AI suggestion are both preserved."],
              ].map(([number, item]) => (
                <li key={number} className="flex gap-space-sm">
                  <span className="pt-0.5 font-mono text-[10px] text-outline">{number}</span>
                  <span className="text-body-sm text-on-surface-variant">{item}</span>
                </li>
              ))}
            </ol>

            <p className="mt-8 border-t border-outline-variant pt-4 font-mono text-[10px] uppercase leading-5 tracking-[0.1em] text-outline">
              The AI proposes.
              <br />
              The examiner decides.
            </p>
          </aside>
        </div>
      </div>
    </div>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-label-md text-on-surface-variant" htmlFor={htmlFor}>
      <span>{label}</span>
      {children}
    </label>
  );
}
