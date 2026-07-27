import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { GmailCard } from "../GmailCard";
import {
  findCatalogModel,
  ModelPicker,
  ModelTuningControls,
} from "../ModelPicker";
import { SecretsForm } from "../forms/SecretsForm";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";
import { useGmailConnectOutcome } from "../use-gmail";
import { useModelCatalog } from "../use-model-catalog";
import { useSaveSecrets, useSecrets } from "../use-secrets";

type ModelsDoc = {
  cheapModel: string;
  midModel: string;
  premiumModel: string;
  cheapReasoningEffort: string | null;
  midReasoningEffort: string | null;
  premiumReasoningEffort: string | null;
  cheapResponseVerbosity: string | null;
  midResponseVerbosity: string | null;
  premiumResponseVerbosity: string | null;
};

type ModelField = {
  key: "cheapModel" | "midModel" | "premiumModel";
  effortKey: "cheapReasoningEffort" | "midReasoningEffort" | "premiumReasoningEffort";
  verbosityKey: "cheapResponseVerbosity" | "midResponseVerbosity" | "premiumResponseVerbosity";
  label: string;
};

const MODEL_FIELDS: ModelField[] = [
  {
    key: "cheapModel",
    effortKey: "cheapReasoningEffort",
    verbosityKey: "cheapResponseVerbosity",
    label: "Cheap tier model",
  },
  {
    key: "midModel",
    effortKey: "midReasoningEffort",
    verbosityKey: "midResponseVerbosity",
    label: "Mid tier model",
  },
  {
    key: "premiumModel",
    effortKey: "premiumReasoningEffort",
    verbosityKey: "premiumResponseVerbosity",
    label: "Premium tier model",
  },
];

export function KeysSettingsPage() {
  const secrets = useSecrets();
  const saveSecrets = useSaveSecrets();
  const models = useConfig("/api/config/models");
  const saveModels = useSaveConfig("/api/config/models");
  const catalog = useModelCatalog();
  const { draft, setDraft, dirty, reset } = useDraft(models.data as ModelsDoc | undefined);
  useGmailConnectOutcome();

  if (!secrets.data || !draft) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">API keys</h1>
        <p className="text-sm text-muted-foreground">
          Keys are write-only: once saved, only the last four characters are shown.
        </p>
      </header>
      <SecretsForm statuses={secrets.data} saving={saveSecrets.isPending}
        onSave={(patch) => saveSecrets.mutate(patch)} />
      <Separator />
      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-medium">Model tiers</h2>
        <FieldGroup>
          {MODEL_FIELDS.map((f) => {
            const model = findCatalogModel(catalog.data, draft[f.key]);
            return (
              <Field key={f.key}>
                <FieldLabel htmlFor={f.key}>{f.label}</FieldLabel>
                <ModelPicker
                  id={f.key}
                  value={draft[f.key]}
                  catalog={catalog.data}
                  onChange={(value) => {
                    const next = findCatalogModel(catalog.data, value);
                    setDraft({
                      ...draft,
                      [f.key]: value,
                      [f.effortKey]: next?.reasoningEfforts.includes(
                        draft[f.effortKey] ?? "",
                      )
                        ? draft[f.effortKey]
                        : null,
                      [f.verbosityKey]: next?.responseVerbosityLevels.includes(
                        draft[f.verbosityKey] ?? "",
                      )
                        ? draft[f.verbosityKey]
                        : null,
                    });
                  }}
                />
                {model && (
                  <ModelTuningControls
                    modelId={draft[f.key]}
                    reasoningEffort={draft[f.effortKey]}
                    responseVerbosity={draft[f.verbosityKey]}
                    catalog={catalog.data}
                    onReasoningEffortChange={(value) =>
                      setDraft({ ...draft, [f.effortKey]: value })
                    }
                    onResponseVerbosityChange={(value) =>
                      setDraft({ ...draft, [f.verbosityKey]: value })
                    }
                  />
                )}
              </Field>
            );
          })}
        </FieldGroup>
        <SaveBar dirty={dirty} saving={saveModels.isPending}
          onSave={() => saveModels.mutate(draft as never)}
          onDiscard={reset} />
      </section>
      <Separator />
      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-medium">Connected accounts</h2>
        <GmailCard />
      </section>
    </div>
  );
}
