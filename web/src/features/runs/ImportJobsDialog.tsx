import { useState } from "react";
import { FileUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getToken } from "@/lib/api/client";
import { useQueryClient } from "@tanstack/react-query";
import { useLaunchRun } from "./use-launch-run";

type ImportReport = {
  added: number;
  upgraded: number;
  skipped: number;
  errors: { row: number; reason: string }[];
};

async function postFile(path: string, file: File): Promise<Response> {
  const form = new FormData();
  form.append("file", file);
  const headers: HeadersInit = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${window.location.origin}${path}`, {
    method: "POST",
    body: form,
    headers,
  });
}

async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body?.error?.message ?? "Import failed");
  return body;
}

export function ImportJobsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const { launch } = useLaunchRun();
  const queryClient = useQueryClient();

  async function submit() {
    if (!file || importing) return;
    setError(null);
    setReport(null);
    const suffix = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (![".csv", ".json", ".txt"].includes(suffix)) {
      setError("Choose a .csv, .json, or .txt file");
      return;
    }
    setImporting(true);
    try {
      if (suffix === ".txt") {
        const launched = await launch(
          "importUrls",
          async () => responseBody(await postFile("/api/jobs/import-urls", file)),
        );
        if (launched) onOpenChange(false);
        return;
      }
      const body = (await responseBody(
        await postFile("/api/jobs/import", file),
      )) as ImportReport;
      setReport(body);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["triage"] }),
        queryClient.invalidateQueries({ queryKey: ["shortlist"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
      ]);
    } catch (submitError) {
      setError((submitError as Error).message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import jobs</DialogTitle>
          <DialogDescription>
            CSV/JSON columns: title, company, url, location, jd_text, posted_at.
            A .txt file accepts one posting URL per line and runs in the background.
          </DialogDescription>
        </DialogHeader>
        <label className="space-y-2 text-sm font-medium">
          Import file
          <Input
            type="file"
            accept=".csv,.json,.txt"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
        {report ? (
          <div className="rounded-lg border bg-muted/25 p-3 text-sm" role="status">
            <p className="font-medium">
              {report.added} added · {report.upgraded} upgraded · {report.skipped} skipped
            </p>
            {report.errors.length ? (
              <ul className="mt-2 space-y-1 text-destructive">
                {report.errors.map((item) => (
                  <li key={`${item.row}-${item.reason}`}>
                    Row {item.row}: {item.reason}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!file || importing} onClick={() => void submit()}>
            {importing ? <Spinner data-icon="inline-start" /> : null}
            Import
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ImportJobsButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <FileUp data-icon="inline-start" />
        Import file…
      </Button>
      <ImportJobsDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
