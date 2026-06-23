import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { launchers, useLaunchRun, type ReprocessScope } from "./use-launch-run";

export function PullDialog() {
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState("");
  const { launch } = useLaunchRun();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm">Pull</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pull from connectors</DialogTitle>
          <DialogDescription>
            Fetch fresh postings from every enabled connector and ingest them.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pull-limit">Limit per connector (optional)</Label>
          <Input
            id="pull-limit"
            type="number"
            min={1}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="no limit"
          />
          <p className="text-xs text-muted-foreground">
            Caps postings fetched per connector this run. Leave blank to pull all.
          </p>
        </div>
        <Button
          onClick={async () => {
            const parsed = Number(limit);
            const ok = await launch("pull", () =>
              launchers.pull({ limit: limit && parsed > 0 ? parsed : null }),
            );
            if (ok) setOpen(false);
          }}
        >
          Start pull
        </Button>
      </DialogContent>
    </Dialog>
  );
}

export function DiscoverDialog() {
  const { launch } = useLaunchRun();
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() => launch("discover", () => launchers.discover())}
    >
      Discover
    </Button>
  );
}

export function RefreshButton() {
  const { launch } = useLaunchRun();
  return (
    <Button size="sm" onClick={() => launch("refresh", () => launchers.refresh())}>
      Refresh
    </Button>
  );
}

const REPROCESS_SCOPES: { value: ReprocessScope; label: string }[] = [
  { value: "shortlisted", label: "Re-score shortlist" },
  { value: "rejected:relevance", label: "Reconsider off-target" },
  { value: "rejected:filtered", label: "Reconsider hard-filtered" },
  { value: "all", label: "Everything (non-submitted)" },
];

export function ReprocessDialog() {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<ReprocessScope>("shortlisted");
  const { launch } = useLaunchRun();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline">Reprocess</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reprocess</DialogTitle>
          <DialogDescription>
            Re-run the full funnel over a scope. Can change fit + status. Submitted jobs
            are never touched.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="reprocess-scope">Scope</Label>
          <Select value={scope} onValueChange={(v) => setScope(v as ReprocessScope)}>
            <SelectTrigger id="reprocess-scope" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REPROCESS_SCOPES.map((s) => (
                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          onClick={async () => {
            const ok = await launch("reprocess", () => launchers.reprocess([scope]));
            if (ok) setOpen(false);
          }}
        >
          Start reprocess
        </Button>
      </DialogContent>
    </Dialog>
  );
}
