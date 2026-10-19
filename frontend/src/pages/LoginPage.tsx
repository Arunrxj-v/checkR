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
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)]">
      {/* Institutional identity panel */}
      <div className="relative hidden flex-col justify-between bg-primary-container p-margin text-on-primary lg:flex">
        <div className="flex items-center gap-space-sm">
          <span className="font-display text-headline-sm font-semibold tracking-tight">
            check<span className="text-primary-fixed-dim">R</span>
          </span>
          <span className="rounded border border-white/15 bg-white/5 px-space-xs py-0.5  text-label-sm text-primary-fixed">
            Academic v2.4
          </span>
        </div>

        <div className="max-w-md">
          <div className="mb-space-md flex h-10 w-10 items-center justify-center rounded border border-white/15 bg-white/5">
            <Icon name="verified_user" className="text-[22px] text-primary-fixed" />
          </div>
          <h1 className="font-display text-headline-xl font-semibold tracking-tight">
            Evaluation you can audit, line by line.
          </h1>
          <p className="mt-3  text-body-md text-primary-fixed/80">
            CheckR reads handwritten scripts, proposes criteria-level marks, and hands every decision to the
            examiner. Nothing is finalised without a human judgement on the record.
          </p>
          <ul className="mt-6 space-y-2  text-body-sm text-primary-fixed/85">
            {[
              "Answers segmented to the exact question",
              "Marks proposed against your marking scheme",
              "AI score preserved alongside the teacher's",
              "Immutable, reproducible audit trail",
            ].map((item) => (
              <li key={item} className="flex items-center gap-space-sm">
                <Icon name="check" className="text-[16px] text-verified" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className=" text-label-sm text-primary-fixed/50">
          Human-in-the-loop · The AI proposes, the examiner decides.
        </p>
      </div>

      {/* Form panel */}
      <div className="flex flex-col items-center justify-center bg-background px-margin-mobile py-margin sm:px-margin">
        <div className="w-full max-w-sm">
          {/* Collapsed identity for small screens: wordmark + the promise. */}
          <div className="mb-space-xl lg:hidden">
            <span className="font-display text-headline-lg font-semibold tracking-tight text-primary">
              check<span className="text-secondary">R</span>
            </span>
            <p className="mt-1  text-body-sm text-on-surface-variant">
              Evaluation you can audit, line by line.
            </p>
          </div>

          <h2 className="font-display text-headline-lg font-semibold tracking-tight text-primary">
            {mode === "signin" ? "Sign in to your desk" : "Create an examiner account"}
          </h2>
          <p className="mt-0.5  text-body-sm text-on-surface-variant">
            {mode === "signin"
              ? "Use your institutional credentials to continue."
              : "Set up an account to create examinations and evaluate scripts."}
          </p>

          <form onSubmit={submit} className="mt-space-lg flex flex-col gap-space-md">
            {error ? (
              <p
                role="alert"
                className="flex items-start gap-space-sm rounded border border-error/40 bg-error-container px-space-md py-space-sm  text-body-sm text-on-error-container"
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
              <div className="grid grid-cols-2 gap-space-md">
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
              className="btn-primary mt-space-xs h-10  text-label-md"
            >
              {busy ? <Spinner className="h-4 w-4 border-white/40 border-t-white" /> : null}
              {mode === "signin" ? "Sign in" : "Create account"}
            </button>
          </form>

          {registrationEnabled || demoCredentials ? (
            <div className="mt-space-lg flex flex-wrap items-center justify-between gap-space-sm border-t border-outline-variant pt-space-md">
              {registrationEnabled ? (
                <button
                  type="button"
                  className=" text-label-md text-secondary hover:underline"
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
                  className="ml-auto  text-label-sm text-outline hover:text-on-surface"
                  onClick={useDemoCredentials}
                >
                  Use demo credentials
                </button>
              ) : null}
            </div>
          ) : null}

          {demoCredentials ? (
            <p className="mt-space-md rounded border border-outline-variant bg-surface-container-low px-space-md py-space-sm  text-body-sm text-on-surface-variant">
              <Icon name="info" className="mr-1 text-[14px] align-[-2px]" />
              Development seed account — <span className="font-mono">{demoCredentials.email}</span> /{" "}
              <span className="font-mono">{demoCredentials.password}</span>
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1  text-label-md text-on-surface-variant" htmlFor={htmlFor}>
      <span>{label}</span>
      {children}
    </label>
  );
}
