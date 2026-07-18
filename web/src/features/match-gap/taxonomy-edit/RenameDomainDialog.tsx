import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { usePatchDomain } from "../use-taxonomy";
export function RenameDomainDialog({
  domainId,
  currentLabel,
  open,
  onOpenChange,
}: {
  domainId: string;
  currentLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [label, setLabel] = useState(currentLabel);
  const mutation = usePatchDomain();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename domain</DialogTitle>
          <DialogDescription>
            Use a concise label that describes the grouped skills.
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel htmlFor="domain-label">Label</FieldLabel>
          <Input
            id="domain-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!label.trim() || mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { domainId, body: { label: label.trim() } },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
