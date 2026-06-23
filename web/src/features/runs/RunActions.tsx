import { AddUrlDialog } from "./AddUrlDialog";
import { PullDialog, DiscoverDialog } from "./RunLaunchDialogs";

export function RunActions() {
  return (
    <div className="flex items-center gap-2">
      <PullDialog />
      <DiscoverDialog />
      <AddUrlDialog />
    </div>
  );
}
