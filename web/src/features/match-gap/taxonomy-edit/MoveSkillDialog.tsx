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
import type { CategoryRow, SkillRow } from "../aggregate";
import { useMoveSkill, type NewDomainInput } from "../use-taxonomy";
import { DomainPicker } from "./DomainPicker";

type Category = { slug: string; label: string; kind: "hard" | "soft" };
export function MoveSkillDialog({
  skill,
  categoryRows,
  categories,
  open,
  onOpenChange,
}: {
  skill: SkillRow;
  categoryRows: CategoryRow[];
  categories: Category[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const mutation = useMoveSkill();
  const [domainId, setDomainId] = useState(skill.domainId ?? "");
  const [newDomain, setNewDomain] = useState<NewDomainInput | null>(null);
  const valid = newDomain
    ? Boolean(newDomain.label.trim() && newDomain.category)
    : Boolean(domainId);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move {skill.skill}</DialogTitle>
          <DialogDescription>
            Choose an existing domain or create a new one.
          </DialogDescription>
        </DialogHeader>
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
            disabled={!valid || mutation.isPending}
            onClick={() =>
              mutation.mutate(
                {
                  token: skill.key,
                  ...(newDomain ? { newDomain } : { domainId }),
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Move skill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
