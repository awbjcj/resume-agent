import { LayoutGrid, List } from "lucide-react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { ViewMode } from "./use-view-mode";

export function BoardViewToggle({ view, onChange }: { view: ViewMode; onChange: (view: ViewMode) => void }) {
  return (
    <ToggleGroup
      aria-label="Board view"
      value={[view]}
      onValueChange={(values) => {
        const next = values.at(-1);
        if (next === "cards" || next === "list") onChange(next);
      }}
    >
      <ToggleGroupItem value="cards" aria-label="Card view">
        <LayoutGrid aria-hidden="true" /> Cards
      </ToggleGroupItem>
      <ToggleGroupItem value="list" aria-label="List view">
        <List aria-hidden="true" /> List
      </ToggleGroupItem>
    </ToggleGroup>
  );
}
