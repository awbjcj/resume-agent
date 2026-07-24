import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import type { paths } from "@/lib/api/schema";
import { ResetSectionButton } from "../ResetSectionButton";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";

type PruneDoc = paths["/api/config/prune"]["get"]["responses"][200]["content"]["application/json"];

const RULES: { key: "enableRejected" | "enableLowFit" | "enableStale"; label: string; help: string }[] = [
  { key: "enableRejected", label: "Archive rejected jobs",
    help: "Jobs the discovery filter already rejected" },
  { key: "enableLowFit", label: "Archive low-fit jobs",
    help: "Scored jobs below the fit threshold" },
  { key: "enableStale", label: "Archive stale jobs",
    help: "Postings older than the stale window" },
];

export function PruningSettingsPage() {
  const { data } = useConfig("/api/config/prune");
  const save = useSaveConfig("/api/config/prune");
  const { draft, setDraft, dirty, reset } = useDraft(data as PruneDoc | undefined);

  if (!draft) return <Skeleton className="h-64 w-full" />;
  const setNum = (key: keyof PruneDoc) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setDraft({ ...draft, [key]: Number(e.target.value || 0) });

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Pruning</h1>
          <p className="text-sm text-muted-foreground">
            Archiving is reversible and never touches jobs you have progressed.
          </p>
        </div>
        <ResetSectionButton sectionId="prune" label="Pruning" />
      </header>
      <FieldGroup>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field>
            <FieldLabel htmlFor="fitThreshold">Fit threshold</FieldLabel>
            <Input id="fitThreshold" type="number" value={draft.fitThreshold}
              onChange={setNum("fitThreshold")} />
            <FieldDescription>Archive scored jobs below this fit score</FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="staleDays">Stale after (days)</FieldLabel>
            <Input id="staleDays" type="number" value={draft.staleDays}
              onChange={setNum("staleDays")} />
          </Field>
          <Field>
            <FieldLabel htmlFor="retentionDays">Delete archived after (days)</FieldLabel>
            <Input id="retentionDays" type="number" value={draft.retentionDays}
              onChange={setNum("retentionDays")} />
          </Field>
        </div>
        {RULES.map((rule) => (
          <Field key={rule.key}>
            <div className="flex items-center gap-3">
              <Switch id={rule.key} checked={draft[rule.key]}
                onCheckedChange={(v: boolean) => setDraft({ ...draft, [rule.key]: v })} />
              <div>
                <FieldLabel htmlFor={rule.key}>{rule.label}</FieldLabel>
                <FieldDescription>{rule.help}</FieldDescription>
              </div>
            </div>
          </Field>
        ))}
      </FieldGroup>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate(draft)} onDiscard={reset} />
    </div>
  );
}
