import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { GmailCard } from "../GmailCard";
import { ModelPicker } from "../ModelPicker";
import { SecretsForm } from "../forms/SecretsForm";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";
import { useGmailConnectOutcome } from "../use-gmail";
import { useModelCatalog } from "../use-model-catalog";
import { useSaveSecrets, useSecrets } from "../use-secrets";

type ModelsDoc = { cheapModel: string; midModel: string; premiumModel: string };

const MODEL_FIELDS: { key: keyof ModelsDoc; label: string }[] = [
  { key: "cheapModel", label: "Cheap tier model" },
  { key: "midModel", label: "Mid tier model" },
  { key: "premiumModel", label: "Premium tier model" },
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
          {MODEL_FIELDS.map((f) => (
            <Field key={f.key}>
              <FieldLabel htmlFor={f.key}>{f.label}</FieldLabel>
              <ModelPicker id={f.key} value={draft[f.key]} catalog={catalog.data}
                onChange={(value) => setDraft({ ...draft, [f.key]: value })} />
            </Field>
          ))}
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
