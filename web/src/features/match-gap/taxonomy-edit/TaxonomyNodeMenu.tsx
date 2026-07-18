import { MoreHorizontalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { CategoryRow, SkillRow } from "../aggregate";
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
}: {
  node: MapNode;
  categoryRows: CategoryRow[];
  onAction: (action: TaxonomyMenuAction) => void;
}) {
  if (node.kind === "category") return null;
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
          />
        }
      >
        <MoreHorizontalIcon />
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
