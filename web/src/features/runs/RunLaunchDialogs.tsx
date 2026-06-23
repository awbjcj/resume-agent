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
import { launchers, useLaunchRun, type DiscoverMode } from "./use-launch-run";

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

const DISCOVER_MODES: { value: DiscoverMode; label: string; hint: string }[] = [
  {
    value: "discover",
    label: "Discover",
    hint: "Run the full funnel: extract → relevance → fit-score new jobs.",
  },
  {
    value: "reextract",
    label: "Re-extract metadata",
    hint: "Backfill criteria_json on already-processed jobs. Doesn't change status or fit.",
  },
  {
    value: "rescore",
    label: "Re-score (SIC + location)",
    hint: "Backfill SIC + location on shortlisted jobs. Doesn't change fit or status.",
  },
];

export function DiscoverDialog() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<DiscoverMode>("discover");
  const { launch } = useLaunchRun();
  const active = DISCOVER_MODES.find((m) => m.value === mode)!;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm">Discover</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Discover</DialogTitle>
          <DialogDescription>
            Run the discovery funnel, or a one-off backfill over existing jobs.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="discover-mode">Mode</Label>
          <Select value={mode} onValueChange={(v) => setMode((v as DiscoverMode) ?? "discover")}>
            <SelectTrigger id="discover-mode" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DISCOVER_MODES.map((m) => (
                <SelectItem key={m.value} value={m.value}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{active.hint}</p>
        </div>
        <Button
          onClick={async () => {
            const ok = await launch("discover", () => launchers.discover(mode));
            if (ok) setOpen(false);
          }}
        >
          Start {active.label.toLowerCase()}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
