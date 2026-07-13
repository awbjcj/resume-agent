import { useState } from "react";
import { CheckCircle2, PlugZap, Plus } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { SourceConnectionFields } from "./SourceConnectionFields";
import { connectionBody, EMPTY_SOURCE_DRAFT, isConnectionComplete, type SourceDraft } from "./source-connection";
import { previewSource, useAddSource, type Preview } from "./use-sources";

export function AddSourceDialog() {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<SourceDraft>(EMPTY_SOURCE_DRAFT);
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const addSource = useAddSource();

  const reset = () => {
    setDraft(EMPTY_SOURCE_DRAFT);
    setLabel("");
    setPreview(null);
    setPreviewing(false);
  };
  const updateDraft = (patch: Partial<SourceDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setPreview(null);
  };
  const body = connectionBody(draft, label);

  return (
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) reset(); }}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Plus data-icon="inline-start" aria-hidden="true" /> Add source
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Connect a job source</DialogTitle>
          <DialogDescription>Choose the hiring platform, verify the live board, then add it to discovery.</DialogDescription>
        </DialogHeader>

        <SourceConnectionFields draft={draft} onChange={updateDraft} />
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="source-label">Display name (optional)</FieldLabel>
            <Input id="source-label" value={label} placeholder="Acme" onChange={(event) => { setLabel(event.target.value); setPreview(null); }} />
          </Field>
        </FieldGroup>

        {preview?.ok ? (
          <Alert>
            <CheckCircle2 aria-hidden="true" />
            <AlertTitle>Connection verified</AlertTitle>
            <AlertDescription>{preview.kind} responded with {preview.roleCount ?? 0} matching roles. The source will be checked again when saved.</AlertDescription>
          </Alert>
        ) : null}
        {preview && !preview.ok ? (
          <Alert variant="destructive">
            <PlugZap aria-hidden="true" />
            <AlertTitle>Could not verify this source</AlertTitle>
            <AlertDescription>{preview.error}</AlertDescription>
          </Alert>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="secondary" disabled={!isConnectionComplete(draft) || previewing} onClick={async () => {
            setPreviewing(true);
            try { setPreview(await previewSource(body)); }
            catch (error) { setPreview({ ok: false, url: "", error: (error as Error).message }); }
            finally { setPreviewing(false); }
          }}>
            {previewing ? <Spinner data-icon="inline-start" /> : <PlugZap data-icon="inline-start" aria-hidden="true" />}
            {previewing ? "Checking live board" : "Verify connection"}
          </Button>
          <Button disabled={!preview?.ok || addSource.isPending} onClick={async () => {
            try { await addSource.mutateAsync(body); setOpen(false); reset(); }
            catch (error) { toast.error((error as Error).message); }
          }}>
            {addSource.isPending ? <Spinner data-icon="inline-start" /> : null}
            Add source
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
