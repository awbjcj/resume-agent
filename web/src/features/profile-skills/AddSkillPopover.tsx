import { useState } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
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
import { cn } from "@/lib/utils";
import { useAddSkill, useAddSkillAlias, useProfileSkills } from "./use-profile-skills";

type Category = "unspecified" | "hard" | "soft" | "domain";

const CATEGORY_LABEL: Record<Category, string> = {
  unspecified: "Not sure",
  hard: "Hard skill",
  soft: "Soft skill",
  domain: "Domain",
};

export function AddSkillPopover({ skillName }: { skillName: string }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"new" | "alias">("new");
  const [category, setCategory] = useState<Category>("unspecified");
  const [query, setQuery] = useState("");
  const { data: skills } = useProfileSkills(open && mode === "alias");
  const addSkill = useAddSkill();
  const addAlias = useAddSkillAlias();

  const shown = (skills ?? []).filter((skill) =>
    skill.name.toLowerCase().includes(query.toLowerCase()),
  );

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setMode("new");
      setCategory("unspecified");
      setQuery("");
    }
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            className="size-4 [&_svg]:size-3"
            aria-label={`Add "${skillName}" to your profile`}
            onClick={(event: React.MouseEvent) => event.stopPropagation()}
          />
        }
      >
        <Plus aria-hidden />
      </PopoverTrigger>

      <PopoverContent
        align="start"
        className="w-80"
        onClick={(event) => event.stopPropagation()}
      >
        <PopoverHeader>
          <PopoverTitle>Add &ldquo;{skillName}&rdquo;</PopoverTitle>
          <PopoverDescription>
            Not detected on your profile yet — add it and this gap clears immediately.
          </PopoverDescription>
        </PopoverHeader>

        <div className="mt-3 flex gap-1 rounded-md bg-muted p-1 text-xs font-medium">
          <button
            type="button"
            className={cn(
              "flex-1 rounded px-2 py-1.5",
              mode === "new" ? "bg-background shadow-sm" : "text-muted-foreground",
            )}
            onClick={() => setMode("new")}
          >
            I have this skill
          </button>
          <button
            type="button"
            className={cn(
              "flex-1 rounded px-2 py-1.5",
              mode === "alias" ? "bg-background shadow-sm" : "text-muted-foreground",
            )}
            onClick={() => setMode("alias")}
          >
            Same as a skill I have
          </button>
        </div>

        {mode === "new" ? (
          <div className="mt-3 space-y-3">
            <Select
              items={(Object.keys(CATEGORY_LABEL) as Category[]).map((value) => ({
                value,
                label: CATEGORY_LABEL[value],
              }))}
              value={category}
              onValueChange={(value) => setCategory((value as Category) ?? "unspecified")}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(CATEGORY_LABEL) as Category[]).map((value) => (
                  <SelectItem key={value} value={value}>
                    {CATEGORY_LABEL[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              size="sm"
              className="w-full"
              disabled={addSkill.isPending}
              onClick={() =>
                addSkill.mutate(
                  {
                    name: skillName,
                    category: category === "unspecified" ? null : category,
                  },
                  { onSuccess: () => handleOpenChange(false) },
                )
              }
            >
              Add to my skills
            </Button>
          </div>
        ) : (
          <div className="mt-3">
            <Command>
              <CommandInput
                value={query}
                onValueChange={setQuery}
                placeholder="Search your skills…"
                aria-label="Search your skills"
              />
              <CommandList className="max-h-48">
                {shown.length === 0 && <CommandEmpty>No matching skills</CommandEmpty>}
                {shown.map((skill) => (
                  <CommandItem
                    key={skill.id}
                    disabled={addAlias.isPending}
                    onSelect={() =>
                      addAlias.mutate(
                        { skillId: skill.id, alias: skillName },
                        { onSuccess: () => handleOpenChange(false) },
                      )
                    }
                  >
                    {skill.name}
                  </CommandItem>
                ))}
              </CommandList>
            </Command>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
