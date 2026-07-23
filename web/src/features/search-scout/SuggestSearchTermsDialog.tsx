import { useMemo, useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

import {
  useDiscoverSearchTerms,
  useSearchDiscoverResult,
  type SearchSuggestionRow,
} from "./use-search-discover";

type Kind = SearchSuggestionRow["kind"];

/** Approved terms bucketed into the search-config draft fields. */
export type SearchTermsApplied = {
  keywords: string[];
  titles: string[];
  locations: string[];
  experienceLevels: string[];
  roleAnchors: string[];
  excludeTerms: string[];
};

const KIND_FIELD: Record<Kind, keyof SearchTermsApplied> = {
  keyword: "keywords",
  title: "titles",
  location: "locations",
  seniority: "experienceLevels",
  adjacent_role: "titles",
  role_anchor: "roleAnchors",
  exclude_term: "excludeTerms",
};

const KIND_ORDER: { kind: Kind; label: string }[] = [
  { kind: "keyword", label: "Keywords" },
  { kind: "title", label: "Titles" },
  { kind: "adjacent_role", label: "Adjacent roles" },
  { kind: "location", label: "Locations" },
  { kind: "seniority", label: "Seniority" },
  { kind: "role_anchor", label: "Role anchors" },
  { kind: "exclude_term", label: "Exclude terms" },
];

const rowKey = (row: SearchSuggestionRow) => `${row.kind}:${row.value}`;

export function SuggestSearchTermsDialog({
  onApply,
}: {
  onApply: (added: SearchTermsApplied) => void;
}) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const launch = useDiscoverSearchTerms();
  const { state, result, error } = useSearchDiscoverResult(runId);

  const reset = () => {
    setPrompt("");
    setRunId(null);
    setSelected(new Set());
  };

  const toggle = (key: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const grouped = useMemo(() => {
    const buckets = new Map<Kind, SearchSuggestionRow[]>();
    for (const { kind } of KIND_ORDER) buckets.set(kind, []);
    for (const row of result?.suggestions ?? []) buckets.get(row.kind)?.push(row);
    return buckets;
  }, [result]);

  const addSelected = () => {
    const added: SearchTermsApplied = {
      keywords: [],
      titles: [],
      locations: [],
      experienceLevels: [],
      roleAnchors: [],
      excludeTerms: [],
    };
    for (const row of result?.suggestions ?? []) {
      if (selected.has(rowKey(row))) added[KIND_FIELD[row.kind]].push(row.value);
    }
    onApply(added);
    setOpen(false);
    reset();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) reset();
      }}
    >
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Sparkles data-icon="inline-start" aria-hidden="true" />
        Suggest search terms
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Suggest search terms</DialogTitle>
          <DialogDescription>
            Describe the roles you want. Search Scout recommends keywords, titles, role
            anchors, locations, seniority, and adjacent roles grounded in your profile.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            setSelected(new Set());
            setRunId((await launch.mutateAsync(prompt.trim())).runId);
          }}
        >
          <Field>
            <FieldLabel htmlFor="search-scout-prompt">What are you looking for?</FieldLabel>
            <Textarea
              id="search-scout-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Senior backend roles in fintech, remote, strong Rust and distributed systems"
            />
          </Field>
          <div>
            <Button type="submit" disabled={launch.isPending || prompt.trim().length < 3}>
              {launch.isPending || state === "running" ? (
                <Spinner data-icon="inline-start" />
              ) : null}
              Suggest
            </Button>
          </div>
        </form>

        {state === "running" ? (
          <p className="text-sm text-muted-foreground">Researching search terms…</p>
        ) : null}
        {state === "error" ? (
          <Alert variant="destructive">
            <AlertTitle>Search discovery failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        {state === "done" && result && result.suggestions.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No new terms found</EmptyTitle>
              <EmptyDescription>
                Try describing the role, seniority, or domain more specifically.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : null}
        {state === "done" && result && result.suggestions.length > 0 ? (
          <div className="flex max-h-[50vh] flex-col gap-4 overflow-auto pr-1">
            {KIND_ORDER.map(({ kind, label }) => {
              const rows = grouped.get(kind) ?? [];
              if (rows.length === 0) return null;
              return (
                <section key={kind} aria-labelledby={`scout-${kind}`}>
                  <h3
                    id={`scout-${kind}`}
                    className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    {label}
                  </h3>
                  <ul className="flex flex-col gap-1.5">
                    {rows.map((row) => {
                      const key = rowKey(row);
                      const duplicate = row.status === "duplicate";
                      const citations = row.citations ?? [];
                      return (
                        <li key={key} className="flex items-start gap-2.5">
                          <Checkbox
                            aria-label={`Select ${row.value}`}
                            className="mt-0.5"
                            checked={selected.has(key)}
                            disabled={duplicate}
                            onCheckedChange={() => toggle(key)}
                          />
                          <div className="min-w-0 flex-1">
                            <span className="text-sm font-medium">{row.value}</span>
                            {row.fitScore == null ? null : (
                              <Badge className="ml-2" variant="secondary">
                                {row.fitScore} fit
                              </Badge>
                            )}
                            {duplicate ? (
                              <span className="ml-2 text-xs text-muted-foreground">
                                already in your search
                              </span>
                            ) : null}
                            <span className="block text-xs text-muted-foreground">
                              {row.reason}
                            </span>
                            {citations.length ? (
                              <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                                {citations.map((citation) => (
                                  <a
                                    key={citation.url}
                                    className="inline-flex items-center gap-1 text-xs text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground"
                                    href={citation.url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {citation.title || citation.url}
                                    <ExternalLink data-icon="inline-end" aria-hidden="true" />
                                  </a>
                                ))}
                              </span>
                            ) : null}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        ) : null}

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
          {state === "done" && result?.suggestions.length ? (
            <Button onClick={addSelected} disabled={selected.size === 0}>
              Add selected ({selected.size})
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
