import { AddUrlDialog } from "./AddUrlDialog";
import { ImportJobsButton } from "./ImportJobsDialog";
import {
  PullDialog,
  DiscoverDialog,
  ReprocessDialog,
  RefreshButton,
} from "./RunLaunchDialogs";

export function RunActions() {
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
      <RefreshButton />
      <PullDialog />
      <DiscoverDialog />
      <ReprocessDialog />
      <AddUrlDialog />
      <ImportJobsButton />
    </div>
  );
}
