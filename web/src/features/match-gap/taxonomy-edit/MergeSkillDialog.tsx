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
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SkillRow } from "../aggregate";
import { useMergeSkills } from "../use-taxonomy";
export function MergeSkillDialog({
  skill,
  allSkills,
  open,
  onOpenChange,
}: {
  skill: SkillRow;
  allSkills: SkillRow[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const mutation = useMergeSkills();
  const options = allSkills.filter((item) => item.key !== skill.key);
  const [canonical, setCanonical] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Merge skill</DialogTitle>
          <DialogDescription>
            {skill.skill} becomes an alias of the selected skill.
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel>Canonical skill</FieldLabel>
          <Select
            items={options.map((item) => ({ label: item.skill, value: item.key }))}
            value={canonical || null}
            onValueChange={(value) => value && setCanonical(value)}
          >
            <SelectTrigger className="w-full">
              <SelectValue>
                {canonical ? undefined : "Choose a skill"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {options.map((item) => (
                  <SelectItem key={item.key} value={item.key}>
                    {item.skill}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!canonical || mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { token: skill.key, canonical },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Merge skill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
