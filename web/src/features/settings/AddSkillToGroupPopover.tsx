import { useState, type FormEvent } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  SKILL_CATEGORY_LABELS,
  SKILL_CATEGORY_OPTIONS,
  type SkillCategory,
} from "@/features/profile-skills/skill-categories";
import { useAddSkill } from "@/features/profile-skills/use-profile-skills";

import { useSetSkillGroup } from "./use-matrix";

export function AddSkillToGroupPopover({
  group,
}: {
  group: { slug: string; label: string };
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState<SkillCategory>("unspecified");
  const addSkill = useAddSkill();
  const setGroup = useSetSkillGroup();
  const skillName = name.trim();

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setName("");
      setCategory("unspecified");
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!skillName) return;

    addSkill.mutate(
      {
        name: skillName,
        category: category === "unspecified" ? null : category,
      },
      {
        onSuccess: () => {
          handleOpenChange(false);
          setGroup.mutate({ key: skillName, group: group.slug });
        },
      },
    );
  };

  const pending = addSkill.isPending || setGroup.isPending;

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger render={<Button type="button" variant="outline" size="sm" />}>
        <Plus aria-hidden data-icon="inline-start" />
        Add skill
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <PopoverHeader>
          <PopoverTitle>Add to {group.label}</PopoverTitle>
          <PopoverDescription>
            Add a profile skill and pin it to this category.
          </PopoverDescription>
        </PopoverHeader>
        <form className="space-y-3" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <label className="text-xs font-medium" htmlFor={`skill-name-${group.slug}`}>
              Skill name
            </label>
            <Input
              id={`skill-name-${group.slug}`}
              autoComplete="off"
              autoFocus
              maxLength={200}
              placeholder="e.g. TypeScript"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium" htmlFor={`skill-type-${group.slug}`}>
              Skill type
            </label>
            <Select
              items={SKILL_CATEGORY_OPTIONS}
              value={category}
              onValueChange={(value) =>
                setCategory((value as SkillCategory | null) ?? "unspecified")
              }
            >
              <SelectTrigger id={`skill-type-${group.slug}`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SKILL_CATEGORY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {SKILL_CATEGORY_LABELS[option.value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            type="submit"
            size="sm"
            className="w-full"
            disabled={!skillName || pending}
          >
            {addSkill.isPending ? "Adding…" : "Add to category"}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
