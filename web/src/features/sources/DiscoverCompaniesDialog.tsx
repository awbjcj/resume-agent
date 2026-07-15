import { useState } from "react";
import { Search } from "lucide-react";

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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

import { useAddSource } from "./use-sources";
import { useDiscoverCompanies, useDiscoverResult, type ScoutCandidate } from "./use-discover";

function statusText(row: ScoutCandidate): string {
  if (row.status === "validated") {
    return row.roleCount == null ? "Validated" : `${row.roleCount} roles`;
  }
  if (row.status === "unverified") return "Scrape target";
  if (row.status === "duplicate") return "Already added";
  return "Failed";
}

export function DiscoverCompaniesDialog() {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [added, setAdded] = useState<Set<string>>(new Set());
  const launch = useDiscoverCompanies();
  const { state, result, error } = useDiscoverResult(runId);
  const addSource = useAddSource();

  const reset = () => {
    setPrompt("");
    setRunId(null);
    setSelected(new Set());
    setRowErrors({});
    setAdded(new Set());
  };

  const toggle = (url: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  };

  const addSelected = async () => {
    if (!result) return;
    for (const row of result.candidates.filter((candidate) => selected.has(candidate.url))) {
      const body = row.status === "unverified"
        ? { provider: "scrape" as const, url: row.url, label: row.company, country: "com" as const }
        : { provider: "auto" as const, url: row.url, label: row.company, country: "com" as const };
      try {
        await addSource.mutateAsync(body);
        setAdded((current) => new Set(current).add(row.url));
        setSelected((current) => {
          const next = new Set(current);
          next.delete(row.url);
          return next;
        });
      } catch (caught) {
        setRowErrors((current) => ({
          ...current,
          [row.url]: caught instanceof Error ? caught.message : "Could not add source",
        }));
      }
    }
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
        <Search data-icon="inline-start" aria-hidden="true" />
        Discover companies
      </DialogTrigger>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Discover companies</DialogTitle>
          <DialogDescription>
            Describe companies or a market. Source Scout verifies boards before you approve them.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            setSelected(new Set());
            setRowErrors({});
            setAdded(new Set());
            setRunId((await launch.mutateAsync(prompt.trim())).runId);
          }}
        >
          <Field>
            <FieldLabel htmlFor="source-scout-prompt">What are you looking for?</FieldLabel>
            <Textarea
              id="source-scout-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Anthropic and AI infrastructure startups hiring platform engineers"
            />
          </Field>
          <div>
            <Button type="submit" disabled={launch.isPending || prompt.trim().length < 3}>
              {launch.isPending || state === "running" ? <Spinner data-icon="inline-start" /> : null}
              Discover
            </Button>
          </div>
        </form>

        {state === "running" ? <p className="text-sm text-muted-foreground">Researching and validating boards…</p> : null}
        {state === "error" ? (
          <Alert variant="destructive">
            <AlertTitle>Discovery failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        {state === "done" && result?.candidates.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No new sources found</EmptyTitle>
              <EmptyDescription>Try naming a company or broadening the market description.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : null}
        {state === "done" && result && result.candidates.length > 0 ? (
          <div className="max-h-[50vh] overflow-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">Add</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Why it fits</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.candidates.map((row) => {
                  const scrapeBlocked = row.status === "unverified" && !result.scrapeAvailable;
                  const disabled = scrapeBlocked || row.status === "failed" || row.status === "duplicate" || added.has(row.url);
                  const explanation = scrapeBlocked ? result.scrapeUnavailableReason : rowErrors[row.url] ?? row.error ?? row.reason;
                  return (
                    <TableRow key={`${row.company}:${row.url}`}>
                      <TableCell title={scrapeBlocked ? result.scrapeUnavailableReason ?? undefined : undefined}>
                        <Checkbox
                          aria-label={`Select ${row.company}`}
                          checked={selected.has(row.url)}
                          disabled={disabled}
                          onCheckedChange={() => toggle(row.url)}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{row.company}</div>
                        <div className="max-w-60 truncate text-xs text-muted-foreground">{row.url}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={row.status === "failed" ? "destructive" : "outline"}>
                          {added.has(row.url) ? "Added" : statusText(row)}
                        </Badge>
                      </TableCell>
                      <TableCell className={rowErrors[row.url] ? "text-destructive" : "text-muted-foreground"}>
                        {explanation}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : null}

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
          {state === "done" && result?.candidates.length ? (
            <Button onClick={addSelected} disabled={selected.size === 0 || addSource.isPending}>
              {addSource.isPending ? <Spinner data-icon="inline-start" /> : null}
              Add selected ({selected.size})
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
