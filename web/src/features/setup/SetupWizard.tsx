import { Check } from "lucide-react";
import { Navigate, NavLink, Outlet, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useSetupStatus, type SetupStatus } from "@/features/settings/use-setup-status";
import { cn } from "@/lib/utils";

export const STEPS = [
  { slug: "keys", label: "Keys", done: (s: SetupStatus) => s.secrets.anyLlmKey },
  { slug: "documents", label: "Documents", done: (s: SetupStatus) => s.profile.hasResume },
  { slug: "search", label: "Search", done: (s: SetupStatus) => s.search.configured },
  { slug: "sources", label: "Sources", done: (s: SetupStatus) => s.sources.enabledCount > 0 },
] as const;

export function firstIncompleteStep(status: SetupStatus): string {
  return STEPS.find((step) => !step.done(status))?.slug ?? "finish";
}

export function SetupWizard() {
  const { data: status } = useSetupStatus();
  const navigate = useNavigate();
  return (
    <div className="mx-auto flex min-h-svh w-full max-w-2xl flex-col gap-8 px-5 py-10">
      <header className="flex items-center gap-3">
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.28em] text-primary">
          Résumé Tailor Harness · First-run setup
        </div>
        <Button variant="ghost" size="sm" className="ml-auto"
          onClick={() => {
            localStorage.setItem("resume-tailor-harness-setup-dismissed", "1");
            navigate("/");
          }}>
          Exit setup
        </Button>
      </header>
      <nav aria-label="Setup steps" className="-mx-5 flex items-center gap-2 overflow-x-auto px-5 pb-1">
        {STEPS.map((step, i) => (
          <div key={step.slug} className="flex shrink-0 items-center gap-2">
            {i > 0 && <div className="h-px w-6 shrink-0 bg-border" aria-hidden="true" />}
            <NavLink to={`/setup/${step.slug}`}
              className={({ isActive }) =>
                cn("flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-sm",
                   isActive && "border-primary font-medium")
              }>
              {status && step.done(status) && (
                <Check className="size-3.5 text-primary" aria-hidden="true" />
              )}
              {step.label}
            </NavLink>
          </div>
        ))}
      </nav>
      <main className="flex-1"><Outlet /></main>
    </div>
  );
}

/** Index route for /setup: resumes at the first incomplete step. */
export function SetupIndexRedirect() {
  const { data: status, isLoading } = useSetupStatus();
  if (isLoading || !status) return null;
  return <Navigate to={`/setup/${firstIncompleteStep(status)}`} replace />;
}
