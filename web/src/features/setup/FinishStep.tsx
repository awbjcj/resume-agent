import { Check } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { useSetupStatus } from "@/features/settings/use-setup-status";
import { launchers, useLaunchRun } from "@/features/runs/use-launch-run";
import { useRunStore } from "@/lib/runs/store";
import { STEPS } from "./SetupWizard";

export function FinishStep() {
  const { data: status } = useSetupStatus();
  const { launch } = useLaunchRun();
  const navigate = useNavigate();
  const run = Object.values(useRunStore((s) => s.runs)).find((r) => r.kind === "profile-build");
  const building = run?.status === "running";
  const built = run?.status === "succeeded";
  const buildResult = run?.result as { experiences?: number; projects?: number } | null | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Finish setup</CardTitle>
        <CardDescription>Build the profile from what you've configured.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ul className="flex flex-col gap-2">
          {STEPS.map((step) => (
            <li key={step.slug} className="flex items-center gap-2 text-sm">
              {status && step.done(status) ? (
                <Check className="size-4 text-primary" aria-hidden="true" />
              ) : (
                <span className="size-4 rounded-full border" aria-hidden="true" />
              )}
              {step.label}
            </li>
          ))}
        </ul>

        {building && (
          <div className="flex flex-col gap-2">
            <Progress value={Math.round(run.percent)} aria-label="Profile build progress" />
            <p className="text-sm text-muted-foreground">Building your profile…</p>
          </div>
        )}
        {built && (
          <p className="text-sm text-primary">
            Profile built — {buildResult?.experiences ?? 0} experiences,{" "}
            {buildResult?.projects ?? 0} projects extracted.
          </p>
        )}
      </CardContent>
      <CardFooter className="justify-end gap-2">
        {!built && (
          <Button variant="outline" disabled={building}
            onClick={() => launch("profile-build", () => launchers.profileBuild(), ["setup-status"])}>
            {building ? <Spinner data-icon="inline-start" /> : null}
            {building ? "Building…" : "Build profile"}
          </Button>
        )}
        <Button onClick={() => {
          localStorage.setItem("resume-agent-setup-dismissed", "1");
          navigate("/");
        }}>
          Go to dashboard
        </Button>
      </CardFooter>
    </Card>
  );
}
