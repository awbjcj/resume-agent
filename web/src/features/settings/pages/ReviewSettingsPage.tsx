import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
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
import { modelTierLabel } from "@/i18n/model-labels";
import { cn } from "@/lib/utils";
import type { paths } from "@/lib/api/schema";
import { ResetSectionButton } from "../ResetSectionButton";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig, type ConfigPath } from "../use-config";
import { useDraft } from "../use-draft";

type ReviewDoc = paths["/api/config/review"]["get"]["responses"][200]["content"]["application/json"];
type ReviewerEntry = NonNullable<ReviewDoc["reviewers"]>[number];
type LengthBudget = ReviewDoc["lengthBudget"];
type ModelTier = ReviewDoc["tailorTier"];

const MODEL_TIERS = ["cheap", "mid", "premium"] as const;

const ROSTERS = [
  {
    id: "fast",
    label: "Fast",
    endpoint: "/api/config/review" as ConfigPath,
    description: "Used by default when tailoring a resume.",
  },
  {
    id: "deep",
    label: "Deep",
    endpoint: "/api/config/review-deep" as ConfigPath,
    description: "Used when \"Deep review\" is checked at tailor time — a separate roster, saved separately.",
  },
] as const;

type RosterId = (typeof ROSTERS)[number]["id"];

/** What each shipped reviewer actually judges. The table used to be five bare
 *  names, which made weight and tier look arbitrary. */
type ReviewerNoteKey =
  | "review.reviewerNotes.factCheck"
  | "review.reviewerNotes.atsKeyword"
  | "review.reviewerNotes.recruiter"
  | "review.reviewerNotes.hiringManager"
  | "review.reviewerNotes.concision"
  | "review.reviewerNotes.mustHaveCoverage";

const REVIEWER_NOTE_KEYS: Record<string, ReviewerNoteKey> = {
  "fact-check": "review.reviewerNotes.factCheck",
  "ats-keyword": "review.reviewerNotes.atsKeyword",
  recruiter: "review.reviewerNotes.recruiter",
  "hiring-manager": "review.reviewerNotes.hiringManager",
  concision: "review.reviewerNotes.concision",
  "must-have-coverage": "review.reviewerNotes.mustHaveCoverage",
};

export function ReviewSettingsPage() {
  const [rosterId, setRosterId] = useState<RosterId>("fast");
  // Switching rosters swaps `key` below, which unmounts the form and takes the
  // unsaved draft with it. Tracking the active form's dirty state up here lets
  // the switch ask first instead of silently discarding typing.
  const [dirty, setDirty] = useState(false);
  const [pendingRoster, setPendingRoster] = useState<RosterId | null>(null);
  const roster = ROSTERS.find((r) => r.id === rosterId) ?? ROSTERS[0];

  const requestRoster = (next: RosterId) => {
    if (next === rosterId) return;
    if (dirty) setPendingRoster(next);
    else setRosterId(next);
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold">Review panel</h1>
          <p className="text-sm text-muted-foreground">
            How tailored resumes get written, scored, and sized before they're offered up for approval.
          </p>
        </div>
        <ResetSectionButton sectionId="review" label="Review panel" />
      </header>

      {/* Fast/Deep is the SCOPE of this page, not a setting on it — every
          control below belongs to the selected roster. Rendering it as a
          labelled Field put it in the same visual class as "Max rounds" and
          forced a horizontal Field whose description never aligned. */}
      <div className="flex flex-col gap-1.5 border-b pb-4">
        <ToggleGroup
          aria-label="Roster"
          value={[rosterId]}
          onValueChange={(values) => {
            const next = values.at(-1) as RosterId | undefined;
            if (next) requestRoster(next);
          }}
        >
          {ROSTERS.map((r) => (
            <ToggleGroupItem key={r.id} value={r.id} aria-label={`${r.label} roster`}>
              {r.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {/* Every description occupies the SAME grid cell, with the inactive
            ones kept in flow but invisible. The box is therefore always as
            tall as the longest description at the current width, so switching
            rosters cannot shift the page — and unlike a reserved min-height,
            that stays true at every viewport instead of just the one the
            number was measured at. */}
        <div className="grid text-sm leading-tight text-muted-foreground">
          {ROSTERS.map((r) => (
            <p
              key={r.id}
              aria-hidden={r.id !== rosterId}
              className={cn(
                "col-start-1 row-start-1",
                r.id !== rosterId && "invisible",
              )}
            >
              {r.description}
            </p>
          ))}
        </div>
      </div>

      <Alert>
        <AlertDescription>
          Defaults are sensible — change reviewer weights only if you know why.
        </AlertDescription>
      </Alert>

      <ReviewRosterForm
        key={roster.id}
        endpoint={roster.endpoint}
        onDirtyChange={setDirty}
      />

      <AlertDialog
        open={pendingRoster !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setPendingRoster(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Your edits to the {roster.label} roster haven't been saved. Switching
              rosters will discard them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingRoster) setRosterId(pendingRoster);
                setPendingRoster(null);
              }}
            >
              Discard and switch
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/** A labelled whole-number input bound to one draft field. Twenty-odd of these
 *  by hand is where transcription bugs live. */
function NumberField({
  id, label, description, value, min = 0, onChange, invalid,
}: {
  id: string;
  label: string;
  description?: string;
  value: number;
  min?: number;
  onChange: (value: number) => void;
  invalid?: string;
}) {
  return (
    <Field data-invalid={invalid ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        value={value}
        aria-invalid={invalid ? true : undefined}
        onChange={(e) => onChange(Number(e.target.value || 0))}
      />
      {description && <FieldDescription>{description}</FieldDescription>}
      {invalid && <FieldError>{invalid}</FieldError>}
    </Field>
  );
}

function TierToggle({
  label, value, onChange, nameKey,
}: {
  label: string;
  value: ModelTier;
  onChange: (tier: ModelTier) => void;
  nameKey: "model.tierNames.writer" | "model.tierNames.reviser";
}) {
  const { t } = useTranslation();
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <ToggleGroup
        value={[value]}
        onValueChange={(values) => {
          const tier = values.at(-1) as ModelTier | undefined;
          if (tier) onChange(tier);
        }}
      >
        {MODEL_TIERS.map((tier) => (
          <ToggleGroupItem
            key={tier}
            value={tier}
            aria-label={t("model.tierChoice", {
              tier: modelTierLabel(t, tier),
              name: t(nameKey),
            })}
          >
            {modelTierLabel(t, tier)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </Field>
  );
}

function SwitchField({
  id, label, description, checked, onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    // FieldContent, not a bare div: `fieldVariants.horizontal` only switches
    // from items-center to items-start via `has-[>[data-slot=field-content]]`,
    // so a plain wrapper leaves the switch vertically centred against a
    // two-line label+description block instead of aligned to the label.
    <Field orientation="horizontal">
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
      <FieldContent>
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        <FieldDescription>{description}</FieldDescription>
      </FieldContent>
    </Field>
  );
}

const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3";

function ReviewRosterForm({
  endpoint, onDirtyChange,
}: {
  endpoint: ConfigPath;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation();
  const { data } = useConfig(endpoint);
  const save = useSaveConfig(endpoint);
  const { draft, setDraft, dirty, reset } = useDraft(data as ReviewDoc | undefined);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  if (!draft) return <Skeleton className="h-64 w-full" />;
  const reviewers = draft.reviewers ?? [];
  const budget = draft.lengthBudget;

  const setReviewer = (index: number, patch: Partial<ReviewerEntry>) => {
    setDraft({
      ...draft,
      reviewers: reviewers.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    });
  };
  const setBudget = (patch: Partial<LengthBudget>) =>
    setDraft({ ...draft, lengthBudget: { ...budget, ...patch } });

  // The server 422s on an inverted range (`ReviewConfig._validate_bullet_ranges`).
  // Catching it inline beats a round-trip that reads as "save is broken".
  const roleRangeError =
    budget.minBulletsPerRole > budget.maxBulletsPerRole
      ? "Minimum cannot exceed the maximum."
      : undefined;
  const projectRangeError =
    budget.minBulletsPerProject > budget.maxBulletsPerProject
      ? "Minimum cannot exceed the maximum."
      : undefined;
  const canSave = !roleRangeError && !projectRangeError;

  return (
    <>
      <FieldSet>
        <FieldLegend>Rounds</FieldLegend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <NumberField
            id="maxRounds"
            label="Max rounds"
            min={1}
            description="How many write-and-review passes before the best attempt is kept."
            value={draft.maxRounds}
            onChange={(v) => setDraft({ ...draft, maxRounds: v })}
          />
          <NumberField
            id="scoreThreshold"
            label="Score threshold"
            description="Weighted panel score a round must reach to stop early."
            value={draft.scoreThreshold}
            onChange={(v) => setDraft({ ...draft, scoreThreshold: v })}
          />
        </div>
      </FieldSet>

      <FieldSet>
        <FieldLegend>Pipeline</FieldLegend>
        <SwitchField
          id="merged-advisory"
          label="Merge advisory reviews into one call"
          description="Faster and cheaper; turn off to run each advisory reviewer separately."
          checked={draft.mergedAdvisory}
          onChange={(v) => setDraft({ ...draft, mergedAdvisory: v })}
        />
        <SwitchField
          id="evidence-portfolio-enabled"
          label="Evidence portfolio planning"
          description="Experimental: rank requirements and freeze the work and project evidence used by the writer."
          checked={draft.evidencePortfolioEnabled}
          onChange={(v) => setDraft({ ...draft, evidencePortfolioEnabled: v })}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TierToggle
            label={t("model.tierNames.writer")}
            nameKey="model.tierNames.writer"
            value={draft.tailorTier}
            onChange={(tier) => setDraft({ ...draft, tailorTier: tier })}
          />
          <TierToggle
            label={t("model.tierNames.reviser")}
            nameKey="model.tierNames.reviser"
            value={draft.reviserTier}
            onChange={(tier) => setDraft({ ...draft, reviserTier: tier })}
          />
        </div>
      </FieldSet>

      <FieldSet>
        <FieldLegend>Reviewers</FieldLegend>
        <FieldDescription>
          A gated reviewer blocks the round outright, so it is never scored —
          its weight and score bands are disabled rather than silently ignored.
        </FieldDescription>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Reviewer</TableHead>
              <TableHead>Gate</TableHead>
              <TableHead>Weight</TableHead>
              <TableHead>Score bands</TableHead>
              <TableHead>Model tier</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reviewers.map((r, i) => (
              <TableRow key={r.name}>
                <TableCell className="align-top">
                  <div className="font-medium">{r.name}</div>
                  {REVIEWER_NOTE_KEYS[r.name] && (
                    <div className="max-w-[26ch] text-xs leading-snug text-muted-foreground">
                      {t(REVIEWER_NOTE_KEYS[r.name])}
                    </div>
                  )}
                </TableCell>
                <TableCell className="align-top">
                  <Switch
                    aria-label={`${r.name} gate`}
                    checked={r.gate}
                    onCheckedChange={(v: boolean) => setReviewer(i, { gate: v })}
                  />
                </TableCell>
                <TableCell className="align-top">
                  <Input
                    type="number"
                    aria-label={`${r.name} weight`}
                    className="w-20"
                    // Preserved, not zeroed: un-gating should restore the
                    // weight you had, not hand back a silent 0-weight reviewer.
                    disabled={r.gate}
                    value={r.weight}
                    onChange={(e) => setReviewer(i, { weight: Number(e.target.value || 0) })}
                  />
                  {r.gate && (
                    <div className="mt-1 text-xs text-muted-foreground">not scored</div>
                  )}
                </TableCell>
                <TableCell className="align-top">
                  <Switch
                    aria-label={`${r.name} score bands`}
                    disabled={r.gate}
                    checked={r.scoreBands}
                    onCheckedChange={(v: boolean) => setReviewer(i, { scoreBands: v })}
                  />
                </TableCell>
                <TableCell className="align-top">
                  <Select
                    value={r.modelTier}
                    onValueChange={(v) => v && setReviewer(i, { modelTier: v })}
                  >
                    <SelectTrigger
                      aria-label={t("model.reviewerTier", { reviewer: r.name })}
                      className="w-32"
                    >
                      <SelectValue>{(v) => modelTierLabel(t, String(v ?? r.modelTier))}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {MODEL_TIERS.map((tier) => (
                          <SelectItem key={tier} value={tier}>
                            {modelTierLabel(t, tier)}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </FieldSet>

      <FieldSet>
        <FieldLegend>Resume shape</FieldLegend>
        <FieldDescription>
          Handed to the writer, the reviser, and the advisory panel. Floors are
          clamped to what your profile can actually support, so a minimum never
          asks for invented evidence.
        </FieldDescription>

        <FieldSet className="gap-3">
          <FieldLegend variant="label">Length</FieldLegend>
          <div className={GRID}>
            <NumberField
              id="pageTarget" label="Page target" min={1}
              value={budget.pageTarget}
              onChange={(v) => setBudget({ pageTarget: v })}
            />
            <NumberField
              id="maxExperiences" label="Max experiences"
              value={budget.maxExperiences}
              onChange={(v) => setBudget({ maxExperiences: v })}
            />
            <NumberField
              id="maxProjects" label="Max projects"
              value={budget.maxProjects}
              onChange={(v) => setBudget({ maxProjects: v })}
            />
            <NumberField
              id="maxEvidenceOwners" label="Max work and project entries"
              value={budget.maxEvidenceOwners}
              onChange={(v) => setBudget({ maxEvidenceOwners: v })}
            />
            <NumberField
              id="targetTotalBullets" label="Target total bullets"
              value={budget.targetTotalBullets}
              onChange={(v) => setBudget({ targetTotalBullets: v })}
            />
          </div>
        </FieldSet>

        <FieldSet className="gap-3">
          <FieldLegend variant="label">Depth</FieldLegend>
          <FieldDescription>
            How much each surviving role or project gets to say.
          </FieldDescription>
          <div className={GRID}>
            <NumberField
              id="minBulletsPerRole" label="Min bullets per role"
              value={budget.minBulletsPerRole} invalid={roleRangeError}
              onChange={(v) => setBudget({ minBulletsPerRole: v })}
            />
            <NumberField
              id="maxBulletsPerRole" label="Max bullets per role"
              value={budget.maxBulletsPerRole} invalid={roleRangeError}
              onChange={(v) => setBudget({ maxBulletsPerRole: v })}
            />
            <NumberField
              id="minBulletsPerProject" label="Min bullets per project"
              value={budget.minBulletsPerProject} invalid={projectRangeError}
              onChange={(v) => setBudget({ minBulletsPerProject: v })}
            />
            <NumberField
              id="maxBulletsPerProject" label="Max bullets per project"
              value={budget.maxBulletsPerProject} invalid={projectRangeError}
              onChange={(v) => setBudget({ maxBulletsPerProject: v })}
            />
            <NumberField
              id="minAspectsPerOwner" label="Min aspects per entry"
              description="Distinct kinds of contribution — scope, impact, technique — per entry."
              value={budget.minAspectsPerOwner}
              onChange={(v) => setBudget({ minAspectsPerOwner: v })}
            />
          </div>
        </FieldSet>

        <FieldSet className="gap-3">
          <FieldLegend variant="label">Skills</FieldLegend>
          <FieldDescription>
            A target, not a cap. The skills section renders one comma-joined line
            per category, so about 40 entries cost roughly five lines — trimming
            it saves almost no space and loses keyword coverage.
          </FieldDescription>
          <div className={GRID}>
            <NumberField
              id="targetSkills" label="Target skills"
              value={budget.targetSkills}
              onChange={(v) => setBudget({ targetSkills: v })}
            />
            <NumberField
              id="maxSkillsPerCategory" label="Max skills per category"
              value={budget.maxSkillsPerCategory}
              onChange={(v) => setBudget({ maxSkillsPerCategory: v })}
            />
          </div>
        </FieldSet>
      </FieldSet>

      <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
        <CollapsibleTrigger className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors duration-150 ease-out-strong hover:text-foreground">
          <ChevronRight
            aria-hidden="true"
            className={cn(
              "size-4 transition-transform duration-200 ease-out-strong motion-reduce:transition-none",
              advancedOpen && "rotate-90",
            )}
          />
          Advanced
        </CollapsibleTrigger>
        {/* Base UI measures the panel and publishes --collapsible-panel-height,
            so this transitions to real content height with no magic number.
            The open state IS the variable and the starting/ending styles
            collapse to zero — the same shape components/ui/accordion.tsx uses,
            because those are the attributes Base UI sets on a transition. */}
        <CollapsibleContent className="h-(--collapsible-panel-height) overflow-hidden transition-[height,opacity] duration-200 ease-out-strong data-ending-style:h-0 data-ending-style:opacity-0 data-starting-style:h-0 data-starting-style:opacity-0 motion-reduce:transition-[opacity]">
          <div className="grid grid-cols-1 gap-4 pt-4 sm:grid-cols-2">
            <NumberField
              id="provenanceRetryBudget"
              label="Provenance retry budget"
              description="Extra rounds granted when a round failed only on citation ids. 0 makes a citation slip cost a full round."
              value={draft.provenanceRetryBudget}
              onChange={(v) => setDraft({ ...draft, provenanceRetryBudget: v })}
            />
            <Field>
              <FieldLabel htmlFor="styleGuidePath">Style guide path</FieldLabel>
              <Input
                id="styleGuidePath"
                value={draft.styleGuidePath}
                onChange={(e) => setDraft({ ...draft, styleGuidePath: e.target.value })}
              />
              <FieldDescription>
                Markdown file whose rules are handed to the writer.
              </FieldDescription>
            </Field>
            <div className="sm:col-span-2">
              <SwitchField
                id="early-stop-on-regression"
                label="Stop early on regression"
                description="End the loop when a round scores worse than the best so far, instead of spending the remaining rounds."
                checked={draft.earlyStopOnRegression}
                onChange={(v) => setDraft({ ...draft, earlyStopOnRegression: v })}
              />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <SaveBar
        dirty={dirty}
        saving={save.isPending}
        canSave={canSave}
        onSave={() => save.mutate(draft)}
        onDiscard={reset}
      />
    </>
  );
}
