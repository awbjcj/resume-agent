import { AddUrlDialog } from "./AddUrlDialog";
import { ImportJobsButton } from "./ImportJobsDialog";
import { cn } from "@/lib/utils";
import {
  PullDialog,
  DiscoverDialog,
  ReprocessDialog,
  RefreshButton,
} from "./RunLaunchDialogs";

export function RunActions({ className }: { className?: string }) {
  return (
    <div
      aria-label="Job discovery actions"
      className={cn("flex min-w-0 flex-wrap items-center justify-end gap-2", className)}
      role="group"
    >
      <RefreshButton />
      <PullDialog />
      <DiscoverDialog />
      <ReprocessDialog />
      <AddUrlDialog />
      <ImportJobsButton />
    </div>
  );
}
