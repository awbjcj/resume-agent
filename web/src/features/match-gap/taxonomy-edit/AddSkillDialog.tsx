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
import type { CategoryRow } from "../aggregate";
import { useAddSkill, type NewDomainInput } from "../use-taxonomy";
import { DomainPicker } from "./DomainPicker";
type Category = { slug: string; label: string; kind: "hard" | "soft" };
export function AddSkillDialog({
  categoryRows,
  categories,
  open,
  onOpenChange,
}: {
  categoryRows: CategoryRow[];
  categories: Category[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [token, setToken] = useState("");
  const [domainId, setDomainId] = useState("");
  const [newDomain, setNewDomain] = useState<NewDomainInput | null>(null);
  const mutation = useAddSkill();
  const validTarget = newDomain
    ? Boolean(newDomain.label.trim() && newDomain.category)
    : Boolean(domainId);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add skill</DialogTitle>
          <DialogDescription>
            Add a skill even when it has no current job demand.
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel htmlFor="skill-token">Skill</FieldLabel>
          <Input
            id="skill-token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
        </Field>
        <DomainPicker
          categoryRows={categoryRows}
          categories={categories}
          domainId={domainId}
          newDomain={newDomain}
          onDomainIdChange={setDomainId}
          onNewDomainChange={setNewDomain}
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!token.trim() || !validTarget || mutation.isPending}
            onClick={() =>
              mutation.mutate(
                {
                  token: token.trim(),
                  ...(newDomain ? { newDomain } : { domainId }),
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Add skill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
