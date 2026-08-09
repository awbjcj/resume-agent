import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { paths } from "@/lib/api/schema";
import { ResetSectionButton } from "../ResetSectionButton";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";

type ReviewDoc = paths["/api/config/review"]["get"]["responses"][200]["content"]["application/json"];
type ReviewerEntry = NonNullable<ReviewDoc["reviewers"]>[number];

const MODEL_TIERS = ["cheap", "mid", "premium"];

const DEFAULT_LENGTH_BUDGET = {
  maxExperiences: 4,
  maxProjects: 2,
  maxEvidenceOwners: 5,
  maxBulletsPerRole: 5,
  maxBulletsPerProject: 3,
  targetTotalBullets: 20,
};

export function ReviewSettingsPage() {
  const { data } = useConfig("/api/config/review");
  const save = useSaveConfig("/api/config/review");
  const { draft, setDraft, dirty, reset } = useDraft(data as ReviewDoc | undefined);

  if (!draft) return <Skeleton className="h-64 w-full" />;
  const reviewers = draft.reviewers ?? [];

  const setReviewer = (index: number, patch: Partial<ReviewerEntry>) => {
    const next = reviewers.map((r, i) => (i === index ? { ...r, ...patch } : r));
    setDraft({ ...draft, reviewers: next });
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Review panel</h1>
          <p className="text-sm text-muted-foreground">
            How tailored resumes get scored before they're offered up for approval.
          </p>
        </div>
        <ResetSectionButton sectionId="review" label="Review panel" />
      </header>
      <Alert>
        <AlertDescription>
          Defaults are sensible — change reviewer weights only if you know why.
        </AlertDescription>
      </Alert>
      <FieldGroup>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="maxRounds">Max rounds</FieldLabel>
            <Input id="maxRounds" type="number" value={draft.maxRounds}
              onChange={(e) => setDraft({ ...draft, maxRounds: Number(e.target.value || 0) })} />
          </Field>
          <Field>
            <FieldLabel htmlFor="scoreThreshold">Score threshold</FieldLabel>
            <Input id="scoreThreshold" type="number" value={draft.scoreThreshold}
              onChange={(e) => setDraft({ ...draft, scoreThreshold: Number(e.target.value || 0) })} />
          </Field>
        </div>
      </FieldGroup>
      <FieldSet>
        <FieldLegend>Pipeline</FieldLegend>
        <Field orientation="horizontal">
          <Switch
            id="merged-advisory"
            checked={draft.mergedAdvisory}
            onCheckedChange={(checked: boolean) =>
              setDraft({ ...draft, mergedAdvisory: checked })}
          />
          <div className="flex flex-col gap-0.5">
            <FieldLabel htmlFor="merged-advisory">
              Merge advisory reviews into one call
            </FieldLabel>
            <FieldDescription>
              Faster and cheaper; turn off to run each advisory reviewer separately.
            </FieldDescription>
          </div>
        </Field>
        <Field orientation="horizontal">
          <Switch
            id="evidence-portfolio-enabled"
            checked={draft.evidencePortfolioEnabled}
            onCheckedChange={(checked: boolean) =>
              setDraft({ ...draft, evidencePortfolioEnabled: checked })}
          />
          <div className="flex flex-col gap-0.5">
            <FieldLabel htmlFor="evidence-portfolio-enabled">
              Evidence portfolio planning
            </FieldLabel>
            <FieldDescription>
              Experimental: rank requirements and freeze the work and project evidence used by the writer.
            </FieldDescription>
          </div>
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel>Writer model tier</FieldLabel>
            <ToggleGroup
              value={[draft.tailorTier]}
              onValueChange={(values) => {
                const tier = values.at(-1) as ReviewDoc["tailorTier"] | undefined;
                if (tier) setDraft({ ...draft, tailorTier: tier });
              }}
            >
              {MODEL_TIERS.map((tier) => (
                <ToggleGroupItem
                  key={tier}
                  value={tier}
                  aria-label={`${tier} writer tier`}
                >
                  {tier}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </Field>
          <Field>
            <FieldLabel>Reviser model tier</FieldLabel>
            <ToggleGroup
              value={[draft.reviserTier]}
              onValueChange={(values) => {
                const tier = values.at(-1) as ReviewDoc["reviserTier"] | undefined;
                if (tier) setDraft({ ...draft, reviserTier: tier });
              }}
            >
              {MODEL_TIERS.map((tier) => (
                <ToggleGroupItem
                  key={tier}
                  value={tier}
                  aria-label={`${tier} reviser tier`}
                >
                  {tier}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </Field>
        </div>
      </FieldSet>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Reviewer</TableHead>
            <TableHead>Gate</TableHead>
            <TableHead>Weight</TableHead>
            <TableHead>Model tier</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {reviewers.map((r, i) => (
            <TableRow key={r.name}>
              <TableCell>
                <div className="font-medium">{r.name}</div>
                {r.name === "fact-check" && (
                  <div className="text-xs text-muted-foreground">
                    Blocking — unsupported claims fail the round
                  </div>
                )}
              </TableCell>
              <TableCell>
                <Switch aria-label={`${r.name} gate`} checked={r.gate}
                  onCheckedChange={(v: boolean) => setReviewer(i, { gate: v })} />
              </TableCell>
              <TableCell>
                <Input type="number" aria-label={`${r.name} weight`} className="w-20"
                  value={r.weight} onChange={(e) => setReviewer(i, { weight: Number(e.target.value || 0) })} />
              </TableCell>
              <TableCell>
                <Select value={r.modelTier}
                  onValueChange={(v) => v && setReviewer(i, { modelTier: v })}>
                  <SelectTrigger aria-label={`${r.name} model tier`} className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {MODEL_TIERS.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <FieldSet>
        <FieldLegend>Length budget</FieldLegend>
        <Field>
          <div className="flex items-center gap-3">
            <Switch id="length-budget-enabled" checked={draft.lengthBudget != null}
              onCheckedChange={(v: boolean) =>
                setDraft({ ...draft, lengthBudget: v ? DEFAULT_LENGTH_BUDGET : null })} />
            <FieldLabel htmlFor="length-budget-enabled">Enforce a length budget</FieldLabel>
          </div>
        </Field>
        {draft.lengthBudget && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field>
              <FieldLabel htmlFor="maxExperiences">Max experiences</FieldLabel>
              <Input id="maxExperiences" type="number" value={draft.lengthBudget.maxExperiences}
                onChange={(e) => setDraft({
                  ...draft,
                  lengthBudget: { ...draft.lengthBudget!, maxExperiences: Number(e.target.value || 0) },
                })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="maxProjects">Max projects</FieldLabel>
              <Input id="maxProjects" type="number" value={draft.lengthBudget.maxProjects}
                onChange={(e) => setDraft({
                  ...draft,
                  lengthBudget: { ...draft.lengthBudget!, maxProjects: Number(e.target.value || 0) },
                })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="maxEvidenceOwners">Max work and project entries</FieldLabel>
              <Input id="maxEvidenceOwners" type="number" value={draft.lengthBudget.maxEvidenceOwners}
                onChange={(e) => setDraft({
                  ...draft,
                  lengthBudget: { ...draft.lengthBudget!, maxEvidenceOwners: Number(e.target.value || 0) },
                })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="maxBulletsPerRole">Max bullets per role</FieldLabel>
              <Input id="maxBulletsPerRole" type="number" value={draft.lengthBudget.maxBulletsPerRole}
                onChange={(e) => setDraft({
                  ...draft,
                  lengthBudget: { ...draft.lengthBudget!, maxBulletsPerRole: Number(e.target.value || 0) },
                })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="maxBulletsPerProject">Max bullets per project</FieldLabel>
              <Input id="maxBulletsPerProject" type="number" value={draft.lengthBudget.maxBulletsPerProject}
                onChange={(e) => setDraft({
                  ...draft,
                  lengthBudget: { ...draft.lengthBudget!, maxBulletsPerProject: Number(e.target.value || 0) },
                })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="targetTotalBullets">Target total bullets</FieldLabel>
              <Input id="targetTotalBullets" type="number" value={draft.lengthBudget.targetTotalBullets}
                onChange={(e) => setDraft({
                  ...draft,
                  lengthBudget: { ...draft.lengthBudget!, targetTotalBullets: Number(e.target.value || 0) },
                })} />
            </Field>
          </div>
        )}
      </FieldSet>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate(draft)} onDiscard={reset} />
    </div>
  );
}
