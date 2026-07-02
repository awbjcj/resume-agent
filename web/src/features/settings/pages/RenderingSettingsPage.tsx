import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { paths } from "@/lib/api/schema";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";

type RenderDoc = paths["/api/config/render"]["get"]["responses"][200]["content"]["application/json"];

export function RenderingSettingsPage() {
  const { data } = useConfig("/api/config/render");
  const save = useSaveConfig("/api/config/render");
  const { draft, setDraft, dirty, reset } = useDraft(data as RenderDoc | undefined);

  if (!draft) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Rendering</h1>
        <p className="text-sm text-muted-foreground">
          Where the Typst template lives and where rendered resumes are written.
        </p>
      </header>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="templatePath">Template path</FieldLabel>
          <Input id="templatePath" value={draft.templatePath}
            onChange={(e) => setDraft({ ...draft, templatePath: e.target.value })} />
          <FieldDescription>Typst template used for rendered resumes</FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="outputDir">Output directory</FieldLabel>
          <Input id="outputDir" value={draft.outputDir}
            onChange={(e) => setDraft({ ...draft, outputDir: e.target.value })} />
        </Field>
      </FieldGroup>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate(draft)} onDiscard={reset} />
    </div>
  );
}
