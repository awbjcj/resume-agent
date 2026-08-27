import { useId, useState } from "react";
import { Archive, Download, Upload } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getToken, openDownload } from "@/lib/api/client";

export function DataArchiveCard({
  title,
  description,
  exportLabel,
  exportPath,
  importPath,
  successMessage,
}: {
  title: string;
  description: string;
  exportLabel: string;
  exportPath: string;
  importPath: string;
  successMessage: string;
}) {
  const fileId = useId();
  const confirmId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [importing, setImporting] = useState(false);

  async function importArchive() {
    if (!file || confirmText !== "REPLACE" || importing) return;
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const headers: HeadersInit = {};
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(
        `${window.location.origin}${importPath}?confirm=REPLACE`,
        { method: "POST", headers, body: form },
      );
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body?.error?.message ?? "Import failed");
      }
      toast.success(successMessage);
      window.location.reload();
    } catch (error) {
      toast.error((error as Error).message);
      setImporting(false);
    }
  }

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <Archive aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle>
              <h3>{title}</h3>
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge variant="outline">Portable archive</Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-6 text-muted-foreground">
          Exports are compressed tar.gz files. Keep archives private because they may
          contain workspace credentials and source data.
        </p>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-end sm:gap-3">
        <Button className="w-full sm:w-auto" variant="outline" onClick={() => void openDownload(exportPath)}>
          <Download data-icon="inline-start" />
          {exportLabel}
        </Button>
        <AlertDialog>
          <AlertDialogTrigger render={<Button className="w-full sm:w-auto" variant="destructive" />}>
            <Upload data-icon="inline-start" />
            Import archive
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogMedia>
                <Upload aria-hidden="true" />
              </AlertDialogMedia>
              <AlertDialogTitle>Replace {title.toLowerCase()}?</AlertDialogTitle>
              <AlertDialogDescription>
                This replaces the current data. Export a backup first. Select a
                tar.gz archive and type REPLACE to continue.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor={fileId}>Archive file</FieldLabel>
                <Input
                  id={fileId}
                  type="file"
                  accept=".tar.gz,.tgz,application/gzip"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor={confirmId}>Type REPLACE to confirm</FieldLabel>
                <Input
                  id={confirmId}
                  value={confirmText}
                  autoComplete="off"
                  onChange={(event) => setConfirmText(event.target.value)}
                />
              </Field>
            </FieldGroup>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={importing}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                disabled={!file || confirmText !== "REPLACE" || importing}
                onClick={(event) => {
                  event.preventDefault();
                  void importArchive();
                }}
              >
                {importing ? <Spinner data-icon="inline-start" /> : null}
                Replace data
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardFooter>
    </Card>
  );
}
