import { Skeleton } from "@/components/ui/skeleton";
import { SuggestSearchTermsDialog } from "@/features/search-scout/SuggestSearchTermsDialog";
import { SearchConfigForm } from "../forms/SearchConfigForm";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useDraft } from "../use-draft";

const dedupe = (existing: string[] | undefined, added: string[]) =>
  Array.from(new Set([...(existing ?? []), ...added]));

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
        <SuggestSearchTermsDialog
          onApply={(added) =>
            setDraft({
              ...draft,
              keywords: dedupe(draft.keywords, added.keywords),
              titles: dedupe(draft.titles, added.titles),
              locations: dedupe(draft.locations, added.locations),
              experienceLevels: dedupe(
                draft.experienceLevels,
                added.experienceLevels,
              ),
              roleAnchors: dedupe(draft.roleAnchors, added.roleAnchors),
              excludeTerms: dedupe(draft.excludeTerms, added.excludeTerms),
            })
          }
        />
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
