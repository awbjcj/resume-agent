import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { SkillRow } from "../aggregate";
import { useRemoveSkill } from "../use-taxonomy";
export function RemoveSkillDialog({
  skill,
  open,
  onOpenChange,
}: {
  skill: SkillRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const mutation = useRemoveSkill();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Remove {skill.skill}?</DialogTitle>
          <DialogDescription>
            Hides {skill.skill} from the constellation. You can re-add it
            anytime.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { token: skill.key },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Remove skill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
