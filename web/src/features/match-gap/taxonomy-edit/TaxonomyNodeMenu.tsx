import { MoreHorizontalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { UNASSIGNED_ID, type CategoryRow, type SkillRow } from "../aggregate";
import type { MapNode } from "../skill-map-layout";

export type TaxonomyMenuAction =
  | { type: "add-skill" }
  | {
      type: "move-skill" | "merge-skill" | "remove-skill" | "open-details";
      skill: SkillRow;
    }
  | { type: "rename-domain"; domainId: string; label: string }
  | { type: "change-category"; domainId: string; categorySlug: string }
  | { type: "merge-domain"; domainId: string };

export function TaxonomyNodeMenu({
  node,
  categoryRows,
  onAction,
  className,
}: {
  node: MapNode;
  categoryRows: CategoryRow[];
  onAction: (action: TaxonomyMenuAction) => void;
  className?: string;
}) {
  if (node.kind === "category") return null;
  // The synthetic "Unassigned" domain has no persisted id; domain edits on it
  // would 404. Its skill leaves remain editable.
  if (node.kind === "domain" && node.entityKey === UNASSIGNED_ID) return null;
  const categorySlug =
    categoryRows.find((category) =>
      category.domains.some((domain) => domain.id === node.entityKey),
    )?.slug ?? "other";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={`Edit ${node.label}`}
            // A compact bordered chip pinned to the node's corner: legible over
            // any pill colour, dimmed until the node is hovered/focused so a
            // dense map stays calm, and always reachable by keyboard.
            className={cn(
              "size-6 rounded-full border border-border bg-card text-muted-foreground opacity-70 shadow-sm transition hover:bg-accent hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100",
              className,
            )}
          />
        }
      >
        <MoreHorizontalIcon className="size-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuGroup>
          {node.kind === "skill" && node.skill ? (
            <>
              <DropdownMenuItem
                onClick={() =>
                  onAction({ type: "open-details", skill: node.skill! })
                }
              >
                Open details
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  onAction({ type: "move-skill", skill: node.skill! })
                }
              >
                Move skill
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  onAction({ type: "merge-skill", skill: node.skill! })
                }
              >
                Merge skill
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={() =>
                  onAction({ type: "remove-skill", skill: node.skill! })
                }
              >
                Remove skill
              </DropdownMenuItem>
            </>
          ) : (
            <>
              <DropdownMenuItem
                onClick={() =>
                  onAction({
                    type: "rename-domain",
                    domainId: node.entityKey,
                    label: node.label,
                  })
                }
              >
                Rename domain
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  onAction({
                    type: "change-category",
                    domainId: node.entityKey,
                    categorySlug,
                  })
                }
              >
                Change category
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  onAction({ type: "merge-domain", domainId: node.entityKey })
                }
              >
                Merge domain
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
