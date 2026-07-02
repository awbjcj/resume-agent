import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";

export function StyleGuideSettingsPage() {
  const { data } = useConfig("/api/config/style-guide");
  const save = useSaveConfig("/api/config/style-guide");
  const { draft, setDraft, dirty, reset } = useDraft(data?.content);

  if (draft === null) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Style guide</h1>
        <p className="text-sm text-muted-foreground">
          House style for tailored bullets — the tailor and reviewers read this.
        </p>
      </header>
      <Field>
        <FieldLabel htmlFor="style-guide">Style guide</FieldLabel>
        <Textarea id="style-guide" value={draft} rows={20}
          className="font-mono text-sm"
          onChange={(e) => setDraft(e.target.value)} />
        <FieldDescription>{draft.length} characters · Markdown</FieldDescription>
      </Field>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate({ content: draft })}
        onDiscard={reset} />
    </div>
  );
}
