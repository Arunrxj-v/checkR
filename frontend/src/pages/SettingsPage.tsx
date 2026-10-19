import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useCrumbs } from "@/components/layout/AppShell";
import { PageContainer, PageHeader } from "@/components/layout/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { Skeleton, Spinner } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toaster";
import { useAuth } from "@/auth/AuthContext";
import { authApi, systemApi } from "@/lib/api";
import { formatDateTime, titleCase } from "@/lib/format";

import { errorText } from "./ExamsPage";

export function SettingsPage() {
  useCrumbs([{ label: "Settings" }]);
  const { user, refreshUser } = useAuth();
  const { notify } = useToast();

  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: () => systemApi.settings() });
  const auditQuery = useQuery({ queryKey: ["audit-logs"], queryFn: () => systemApi.auditLogs({ limit: 25 }) });

  const [profile, setProfile] = useState({
    full_name: user?.full_name ?? "",
    department: user?.department ?? "",
    institution: user?.institution ?? "",
  });
  const [password, setPassword] = useState({ current: "", next: "" });

  const profileMutation = useMutation({
    mutationFn: () =>
      authApi.updateMe({
        full_name: profile.full_name.trim(),
        department: profile.department.trim() || undefined,
        institution: profile.institution.trim() || undefined,
      }),
    onSuccess: async () => {
      await refreshUser();
      notify("Profile updated", { tone: "verified" });
    },
    onError: (err) => notify("Could not update profile", { tone: "critical", detail: errorText(err) }),
  });

  const passwordMutation = useMutation({
    mutationFn: () => authApi.changePassword(password.current, password.next),
    onSuccess: () => {
      notify("Password changed", { tone: "verified" });
      setPassword({ current: "", next: "" });
    },
    onError: (err) => notify("Could not change password", { tone: "critical", detail: errorText(err) }),
  });

  const settings = settingsQuery.data;

  return (
    <PageContainer>
      <PageHeader title="Settings" description="Runtime configuration, your account and the audit trail." />

      <div className="grid grid-cols-1 gap-space-lg xl:grid-cols-2">
        {/* Runtime configuration */}
        <section className="panel flex flex-col">
          <SectionHeader icon="tune" title="Evaluation engine" />
          {settingsQuery.isLoading ? (
            <div className="flex flex-col gap-space-sm p-space-md">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
            </div>
          ) : settings ? (
            <dl className="divide-y divide-outline-variant  text-body-sm">
              <Row label="Application" value={`${settings.app_name} · v${settings.version}`} />
              <Row label="Environment" value={titleCase(settings.environment)} />
              <Row
                label="AI provider"
                value={
                  <span className="flex items-center gap-space-xs">
                    <StatusBadge tone={settings.ai.is_mock ? "review" : "verified"} label={settings.ai.is_mock ? "Mock" : "Live"} />
                    <span className="font-mono">{settings.ai.provider}</span>
                  </span>
                }
              />
              <Row label="Model" value={<span className="font-mono">{settings.ai.model || "—"}</span>} />
              <Row
                label="Confidence thresholds"
                value={
                  <span className="font-mono">
                    high ≥ {settings.ai.confidence_high} · medium ≥ {settings.ai.confidence_medium}
                  </span>
                }
              />
              <Row label="Storage" value={<span className="font-mono">{settings.storage.provider}</span>} />
              <Row
                label="Upload limits"
                value={`${settings.uploads.max_upload_mb} MB · ${settings.uploads.max_submission_pages} pages`}
              />
              <Row
                label="Accepted types"
                value={<span className="font-mono">{settings.uploads.accepted_types.join(", ")}</span>}
              />
            </dl>
          ) : (
            <p className="p-space-md  text-body-sm text-critical-fg">{errorText(settingsQuery.error)}</p>
          )}
          {settings?.ai.is_mock ? (
            <p className="m-space-md mt-0 flex items-start gap-space-sm rounded border border-review-border bg-review-bg px-space-sm py-2  text-body-sm text-review-fg">
              <Icon name="science" className="text-[16px]" />
              The mock provider returns deterministic results. Set <span className="font-mono">AI_PROVIDER</span> and{" "}
              <span className="font-mono">AI_API_KEY</span> in the environment to evaluate with a real model.
            </p>
          ) : null}
        </section>

        {/* Account */}
        <section className="panel flex flex-col">
          <SectionHeader icon="manage_accounts" title="Your account" />
          <div className="flex flex-col gap-space-md p-space-md">
            <div className="grid grid-cols-1 gap-space-md sm:grid-cols-2">
              <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
                Full name
                <input className="field" value={profile.full_name} onChange={(e) => setProfile((p) => ({ ...p, full_name: e.target.value }))} />
              </label>
              <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
                Email
                <input className="field font-mono" value={user?.email ?? ""} disabled />
              </label>
              <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
                Department
                <input className="field" value={profile.department} onChange={(e) => setProfile((p) => ({ ...p, department: e.target.value }))} />
              </label>
              <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
                Institution
                <input className="field" value={profile.institution} onChange={(e) => setProfile((p) => ({ ...p, institution: e.target.value }))} />
              </label>
            </div>
            <div className="flex justify-end">
              <button type="button" className="btn-primary px-space-md py-1.5  text-label-md" onClick={() => profileMutation.mutate()} disabled={profileMutation.isPending}>
                {profileMutation.isPending ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : null}
                Save profile
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-space-md border-t border-outline-variant p-space-md">
            <h3 className=" text-label-md font-semibold uppercase tracking-wider text-primary">Change password</h3>
            <div className="grid grid-cols-1 gap-space-md sm:grid-cols-2">
              <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
                Current password
                <input type="password" className="field" value={password.current} onChange={(e) => setPassword((p) => ({ ...p, current: e.target.value }))} />
              </label>
              <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
                New password
                <input type="password" className="field" value={password.next} onChange={(e) => setPassword((p) => ({ ...p, next: e.target.value }))} />
              </label>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                className="btn-secondary px-space-md py-1.5  text-label-md"
                onClick={() => passwordMutation.mutate()}
                disabled={passwordMutation.isPending || password.next.length < 8 || !password.current}
              >
                {passwordMutation.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
                Update password
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* Audit log */}
      <section className="panel flex flex-col">
        <SectionHeader icon="history" title="Audit trail" note="Immutable record of every evaluation and review action." />
        {auditQuery.isLoading ? (
          <div className="flex flex-col gap-space-sm p-space-md">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : (auditQuery.data?.items ?? []).length === 0 ? (
          <p className="p-space-md  text-body-sm text-on-surface-variant">No audit entries yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-outline-variant bg-surface-container-low/70  text-label-sm uppercase tracking-wider text-on-surface-variant">
                  <th className="px-space-md py-2 font-medium">When</th>
                  <th className="px-space-md py-2 font-medium">Action</th>
                  <th className="px-space-md py-2 font-medium">Entity</th>
                  <th className="px-space-md py-2 font-medium">Actor</th>
                  <th className="px-space-md py-2 font-medium">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant  text-body-sm">
                {(auditQuery.data?.items ?? []).map((entry) => (
                  <tr key={entry.id} className="transition-colors hover:bg-surface-container-low/40">
                    <td className="whitespace-nowrap px-space-md py-2 font-mono text-label-sm text-on-surface-variant">
                      {formatDateTime(entry.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-space-md py-2">
                      <span className="rounded bg-surface-container px-1.5 py-0.5 font-mono text-label-sm text-on-surface-variant">
                        {entry.action}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-space-md py-2 font-mono text-label-sm text-outline">
                      {entry.entity_type}
                    </td>
                    <td className="whitespace-nowrap px-space-md py-2 text-on-surface-variant">{entry.actor_email ?? "system"}</td>
                    <td className="px-space-md py-2 text-on-surface-variant">{entry.description ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </PageContainer>
  );
}

function SectionHeader({ icon, title, note }: { icon: string; title: string; note?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-outline-variant px-space-md py-space-sm">
      <div className="flex items-center gap-space-sm">
        <Icon name={icon} className="text-[18px] text-primary" />
        <h2 className=" text-label-md font-semibold uppercase tracking-wider text-primary">{title}</h2>
      </div>
      {note ? <span className=" text-label-sm text-outline">{note}</span> : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-space-md px-space-md py-2">
      <dt className="text-on-surface-variant">{label}</dt>
      <dd className="text-right text-on-surface">{value}</dd>
    </div>
  );
}
