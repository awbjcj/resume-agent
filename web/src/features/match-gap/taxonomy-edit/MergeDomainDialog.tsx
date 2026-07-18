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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { UNASSIGNED_ID, type CategoryRow } from "../aggregate";
import { useMergeDomains } from "../use-taxonomy";
export function MergeDomainDialog({
  domainId,
  categoryRows,
  open,
  onOpenChange,
}: {
  domainId: string;
  categoryRows: CategoryRow[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [into, setInto] = useState("");
  const mutation = useMergeDomains();
  // Exclude the source domain and the render-only "Unassigned" pseudo-domain,
  // which has no persisted id and would 404 as a merge target.
  const isTargetable = (id: string) => id !== domainId && id !== UNASSIGNED_ID;
  const items = categoryRows.flatMap((category) =>
    category.domains.filter((domain) => isTargetable(domain.id)).map((domain) => domain.id),
  );
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Merge domain</DialogTitle>
          <DialogDescription>
            Skills in this domain move to the target; this domain disappears.
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel>Target domain</FieldLabel>
          <Select
            items={items.map((value) => ({ label: value, value }))}
            value={into || null}
            onValueChange={(value) => value && setInto(value)}
          >
            <SelectTrigger className="w-full">
              <SelectValue>{into ? undefined : "Choose a domain"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {categoryRows.map((category) => (
                <SelectGroup key={category.slug}>
                  <SelectLabel>{category.label}</SelectLabel>
                  {category.domains
                    .filter((domain) => isTargetable(domain.id))
                    .map((domain) => (
                      <SelectItem key={domain.id} value={domain.id}>
                        {domain.label}
                      </SelectItem>
                    ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!into || mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { domainId, into },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Merge domain
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
