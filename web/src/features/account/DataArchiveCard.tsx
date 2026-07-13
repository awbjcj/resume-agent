import { useId, useState } from "react";
import { Download, Upload } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        <Button variant="outline" onClick={() => void openDownload(exportPath)}>
          <Download data-icon="inline-start" />
          {exportLabel}
        </Button>
        <AlertDialog>
          <AlertDialogTrigger render={<Button variant="destructive" />}>
            <Upload data-icon="inline-start" />
            Import archive
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Replace {title.toLowerCase()}?</AlertDialogTitle>
              <AlertDialogDescription>
                This replaces the current data. Export a backup first. Select a
                tar.gz archive and type REPLACE to continue.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="space-y-4 py-2">
              <label className="block space-y-2 text-sm font-medium" htmlFor={fileId}>
                Archive file
                <Input
                  id={fileId}
                  type="file"
                  accept=".tar.gz,.tgz,application/gzip"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <label className="block space-y-2 text-sm font-medium" htmlFor={confirmId}>
                Type REPLACE to confirm
                <Input
                  id={confirmId}
                  value={confirmText}
                  autoComplete="off"
                  onChange={(event) => setConfirmText(event.target.value)}
                />
              </label>
            </div>
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
      </CardContent>
    </Card>
  );
}
