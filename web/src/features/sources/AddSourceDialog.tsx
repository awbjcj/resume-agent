import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { previewSource, useAddSource, type Preview } from "./use-sources";

export function AddSourceDialog() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const addSource = useAddSource();

  const reset = () => {
    setUrl("");
    setLabel("");
    setPreview(null);
    setPreviewing(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) reset();
      }}
    >
      <DialogTrigger
        render={
          <Button variant="outline" size="sm">
            <Plus className="size-4" aria-hidden="true" />
            Add source
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add a job source</DialogTitle>
        </DialogHeader>

        <div className="grid gap-2">
          <Label htmlFor="src-url">Careers or board URL</Label>
          <Input
            id="src-url"
            value={url}
            placeholder="https://jobs.example.com/company"
            onChange={(event) => {
              setUrl(event.target.value);
              setPreview(null);
            }}
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="src-label">Display name (optional)</Label>
          <Input
            id="src-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </div>

        <div className="flex min-h-9 flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            disabled={!url.trim() || previewing}
            onClick={async () => {
              setPreviewing(true);
              try {
                setPreview(await previewSource(url.trim(), label.trim() || null));
              } finally {
                setPreviewing(false);
              }
            }}
          >
            {previewing ? "Checking..." : "Preview"}
          </Button>
          {preview?.ok ? (
            <span className="text-sm text-muted-foreground">
              {preview.kind} - {preview.roleCount ?? 0} roles
            </span>
          ) : null}
          {preview && !preview.ok ? (
            <span className="text-sm text-destructive">{preview.error}</span>
          ) : null}
        </div>

        <Button
          disabled={!preview?.ok || addSource.isPending}
          onClick={async () => {
            try {
              await addSource.mutateAsync({ url: url.trim(), label: label.trim() || null });
              setOpen(false);
              reset();
            } catch (error) {
              toast.error((error as Error).message);
            }
          }}
        >
          Add source
        </Button>
      </DialogContent>
    </Dialog>
  );
}
