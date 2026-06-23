import { AddUrlDialog } from "./AddUrlDialog";
import {
  PullDialog,
  DiscoverDialog,
  ReprocessDialog,
  RefreshButton,
} from "./RunLaunchDialogs";

export function RunActions() {
  return (
    <div className="flex items-center gap-2">
      <RefreshButton />
      <PullDialog />
      <DiscoverDialog />
      <ReprocessDialog />
      <AddUrlDialog />
    </div>
  );
}
