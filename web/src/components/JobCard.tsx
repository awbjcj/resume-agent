import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { FitMeter } from "./FitMeter";
import { SkillChip } from "./SkillChip";
import type { ShortlistItem } from "@/lib/filters/types";

export function JobCard({
  row,
  activeSkills,
  onOpen,
  footer,
}: {
  row: ShortlistItem;
  activeSkills: Set<string>;
  onOpen: () => void;
  footer?: ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-3 p-4">
      <button onClick={onOpen} className="flex gap-4 text-left">
        <FitMeter score={row.fitScore} />
        <div className="min-w-0">
          <div className="font-serif text-lg font-semibold">{row.title ?? "—"}</div>
          <div className="text-sm text-muted-foreground">
            {row.company ?? "—"} · {row.location ?? "location n/a"}
          </div>
          {row.skills.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {row.skills.slice(0, 6).map((t) => (
                <SkillChip
                  key={t.name}
                  name={t.name}
                  active={activeSkills.has(t.name.toLowerCase())}
                />
              ))}
            </div>
          )}
          {row.fitRationale && (
            <p className="mt-2 line-clamp-4 text-sm text-muted-foreground">{row.fitRationale}</p>
          )}
        </div>
      </button>
      {footer && <div className="mt-auto">{footer}</div>}
    </Card>
  );
}
