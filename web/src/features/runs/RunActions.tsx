import { Button } from "@/components/ui/button";
import { AddUrlDialog } from "./AddUrlDialog";
import { launchers, useLaunchRun } from "./use-launch-run";

export function RunActions() {
  const { launch } = useLaunchRun();
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" onClick={() => launch("pull", launchers.pull)}>
        Pull
      </Button>
      <Button size="sm" onClick={() => launch("discover", launchers.discover)}>
        Discover
      </Button>
      <AddUrlDialog />
    </div>
  );
}
