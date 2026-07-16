import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ManualEntry } from "@/features/profile-skills/use-profile-skills";
import { useManualSkills, useRemoveManualSkill } from "@/features/profile-skills/use-profile-skills";

function entryLabel(entry: ManualEntry): string {
  if (entry.kind === "new_skill") return entry.name ?? "Unnamed skill";
  return `${entry.aliasText} → ${entry.targetSkillDisplay}`;
}

export function ManualSkillsPanel() {
  const { data: entries, isPending } = useManualSkills();
  const remove = useRemoveManualSkill();

  if (isPending) {
    return <Skeleton className="h-24 w-full" aria-label="Loading manually added skills" />;
  }
  if (!entries || entries.length === 0) return null;

  return (
    <section aria-labelledby="manual-skills-heading">
      <h2 id="manual-skills-heading" className="text-base font-semibold">
        Manually added skills
      </h2>
      <p className="mb-2 text-sm text-muted-foreground">
        Added directly from a job's gap chips. These are replayed automatically the next
        time you rebuild your profile.
      </p>
      <ul className="divide-y border-y">
        {entries.map((entry) => {
          const label = entryLabel(entry);
          return (
            <li
              key={entry.id}
              className="flex items-center justify-between gap-3 py-2.5 text-sm"
            >
              <span>{label}</span>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${label}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(entry.id)}
              >
                <Trash2 aria-hidden />
              </Button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
