import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { BuildReportPanel } from "@/features/profile-sources/BuildReportPanel";
import { SourceManager } from "@/features/profile-sources/SourceManager";
import { useActiveRun } from "@/features/runs/use-active-run";
import { launchers, useLaunchRun } from "@/features/runs/use-launch-run";
import type { paths } from "@/lib/api/schema";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";
import { useSetupStatus } from "../use-setup-status";

type ProfileDoc = paths["/api/config/profile"]["get"]["responses"][200]["content"]["application/json"];

function factsStatusText(builtAt: string | null | undefined): string {
  if (!builtAt) return "Not built yet";
  return `Profile built ${new Date(builtAt).toLocaleString()}`;
}

export function ProfileSettingsPage() {
  const { data } = useConfig("/api/config/profile");
  const save = useSaveConfig("/api/config/profile");
  const { draft, setDraft, dirty, reset } = useDraft(data as ProfileDoc | undefined);
  const setupStatus = useSetupStatus();
  const { launch } = useLaunchRun();
  const building = useActiveRun("profile-build")?.status === "running";

  if (!draft) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Profile & documents</h1>
        <p className="text-sm text-muted-foreground">
          The resume and other source documents the profile is built from.
        </p>
      </header>
      <SourceManager />
      <Separator />
      <Field>
        <FieldLabel htmlFor="githubUsername">GitHub username</FieldLabel>
        <Input id="githubUsername" value={draft.githubUsername ?? ""}
          onChange={(e) => setDraft({ ...draft, githubUsername: e.target.value || null })} />
        <FieldDescription>Optional — pulls public repos into project facts</FieldDescription>
      </Field>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate(draft)} onDiscard={reset} />
      <Separator />
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm text-muted-foreground">
          {factsStatusText(setupStatus.data?.profile.factsBuiltAt)}
        </div>
        <Button
          variant="outline"
          className="ml-auto"
          disabled={building}
          onClick={() =>
            launch("profile-build", () => launchers.profileBuild(), [
              "setup-status",
              "profile-sources",
              "profile-skeleton",
            ])
          }
        >
          {building ? <Spinner data-icon="inline-start" /> : null}
          {building ? "Building…" : "Rebuild profile"}
        </Button>
      </div>
      <BuildReportPanel />
    </div>
  );
}
