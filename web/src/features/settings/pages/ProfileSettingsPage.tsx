import { Button } from "@/components/ui/button";
import { useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";

import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { BuildReportPanel } from "@/features/profile-sources/BuildReportPanel";
import { SourceManager } from "@/features/profile-sources/SourceManager";
import { useCoachSessions } from "@/features/coach/use-coach";
import { useActiveRun } from "@/features/runs/use-active-run";
import { launchers, useLaunchRun } from "@/features/runs/use-launch-run";
import type { paths } from "@/lib/api/schema";
import { ManualSkillsPanel } from "../ManualSkillsPanel";
import { SaveBar } from "../SaveBar";
import { SkillGroupsPanel } from "../SkillGroupsPanel";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";
import { useSetupStatus } from "../use-setup-status";

type ProfileDoc = paths["/api/config/profile"]["get"]["responses"][200]["content"]["application/json"];

function parseRepoList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function factsStatusText(builtAt: string | null | undefined): string {
  if (!builtAt) return "Not built yet";
  return `Profile built ${new Date(builtAt).toLocaleString()}`;
}

export function ProfileSettingsPage() {
  const { data } = useConfig("/api/config/profile");
  const save = useSaveConfig("/api/config/profile");
  const { draft, setDraft, dirty, reset } = useDraft(data as ProfileDoc | undefined);
  const setupStatus = useSetupStatus();
  const coachSessions = useCoachSessions();
  const { launch } = useLaunchRun();
  const building = useActiveRun("profile-build")?.status === "running";
  const [allowText, setAllowText] = useState("");
  const [denyText, setDenyText] = useState("");
  const [limitText, setLimitText] = useState("");
  const [textSeed, setTextSeed] = useState<string | null>(null);

  const nextSeed = data ? JSON.stringify(data) : null;
  if (data && textSeed !== nextSeed) {
    setTextSeed(nextSeed);
    setAllowText((data.githubRepoAllow ?? []).join(", "));
    setDenyText((data.githubRepoDeny ?? []).join(", "));
    setLimitText(String(data.githubRepoLimit));
  }

  if (!draft) return <Skeleton className="h-64 w-full" />;

  const coachRows = coachSessions.data?.sessions ?? [];
  const lastCoach = coachRows[coachRows.length - 1];

  const parsedLimit = Number(limitText);
  const limitValid = Number.isInteger(parsedLimit) && parsedLimit >= 1 && parsedLimit <= 100;

  const discard = () => {
    setAllowText((data?.githubRepoAllow ?? []).join(", "));
    setDenyText((data?.githubRepoDeny ?? []).join(", "));
    setLimitText(String(data?.githubRepoLimit ?? 20));
    reset();
  };

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Profile & documents</h1>
        <p className="text-sm text-muted-foreground">
          The resume and other source documents the profile is built from.
        </p>
      </header>
      <Card className="border-primary/20 bg-gradient-to-br from-card via-card to-primary/[0.05]">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden="true" />
            Profile coach
          </CardTitle>
          <CardDescription>
            {lastCoach
              ? `${lastCoach.topicCount} topics · last session ${new Date(lastCoach.startedAt).toLocaleDateString()}`
              : "Start your first coaching session to uncover grounded profile evidence."}
          </CardDescription>
          <CardAction>
            <Button render={<a href="/coach" />}>
              Open coach
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
          </CardAction>
        </CardHeader>
      </Card>
      <SourceManager />
      <Separator />
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="githubUsername">GitHub username</FieldLabel>
          <Input id="githubUsername" value={draft.githubUsername ?? ""}
            onChange={(e) => setDraft({ ...draft, githubUsername: e.target.value || null })} />
          <FieldDescription>Optional — pulls public repos into project facts.</FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="githubRepoAllow">Always include repositories</FieldLabel>
          <Input
            id="githubRepoAllow"
            value={allowText}
            placeholder="portfolio, flagship-project"
            onChange={(event) => {
              setAllowText(event.target.value);
              setDraft({ ...draft, githubRepoAllow: parseRepoList(event.target.value) });
            }}
          />
          <FieldDescription>Comma-separated repository names that bypass ranking.</FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="githubRepoDeny">Exclude repositories</FieldLabel>
          <Input
            id="githubRepoDeny"
            value={denyText}
            placeholder="archive, experiments"
            onChange={(event) => {
              setDenyText(event.target.value);
              setDraft({ ...draft, githubRepoDeny: parseRepoList(event.target.value) });
            }}
          />
          <FieldDescription>Comma-separated repository names that are never harvested.</FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="githubRepoLimit">Repository limit</FieldLabel>
          <Input
            id="githubRepoLimit"
            type="number"
            min={1}
            max={100}
            value={limitText}
            onChange={(event) => {
              const value = event.target.value;
              setLimitText(value);
              const parsed = Number(value);
              if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 100) {
                setDraft({ ...draft, githubRepoLimit: parsed });
              }
            }}
          />
          <FieldDescription>
            {limitValid
              ? "Maximum ranked repositories to import, from 1 to 100."
              : "Enter a whole number from 1 to 100 to save."}
          </FieldDescription>
        </Field>
      </FieldGroup>
      <SaveBar dirty={dirty} saving={save.isPending} canSave={limitValid}
        onSave={() => save.mutate(draft)} onDiscard={discard} />
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
              "profile-matrix",
            ])
          }
        >
          {building ? <Spinner data-icon="inline-start" /> : null}
          {building ? "Building…" : "Rebuild profile"}
        </Button>
      </div>
      <BuildReportPanel />
      <Separator />
      <SkillGroupsPanel />
      <Separator />
      <ManualSkillsPanel />
    </div>
  );
}
