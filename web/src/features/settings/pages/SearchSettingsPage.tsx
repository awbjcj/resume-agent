import { Sparkles } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { SearchConfigForm } from "../forms/SearchConfigForm";
import { ResetSectionButton } from "../ResetSectionButton";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";

export function SearchSettingsPage() {
  const { data } = useConfig("/api/config/search");
  const save = useSaveConfig("/api/config/search");
  const { draft, setDraft, dirty, reset } = useDraft(data);

  if (!draft) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Search</h1>
          <p className="text-sm text-muted-foreground">
            What discovery looks for. Tighter role anchors mean fewer wasted fetches.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" render={<a href="/scout" />}>
            <Sparkles data-icon="inline-start" aria-hidden="true" />
            Ask the Scout
          </Button>
          <ResetSectionButton sectionId="search" label="Search" />
        </div>
      </header>
      <SearchConfigForm value={draft} onChange={setDraft} />
      <SaveBar
        dirty={dirty}
        saving={save.isPending}
        onSave={() => save.mutate(draft, { onSuccess: (saved) => setDraft(saved) })}
        onDiscard={reset}
      />
    </div>
  );
}
