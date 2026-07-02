import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export function SaveBar({
  dirty, saving, onSave, onDiscard,
}: {
  dirty: boolean; saving: boolean; onSave: () => void; onDiscard: () => void;
}) {
  if (!dirty) return null;
  return (
    <div className="sticky bottom-0 z-10 mt-6 flex items-center gap-3 rounded-lg border bg-background/95 p-3 backdrop-blur">
      <span className="text-sm text-muted-foreground">You have unsaved changes</span>
      <div className="ml-auto flex gap-2">
        <Button variant="outline" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
        <Button onClick={onSave} disabled={saving}>
          {saving ? <Spinner data-icon="inline-start" /> : null}
          Save changes
        </Button>
      </div>
    </div>
  );
}
