import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "./use-launch-run";

export function AddUrlDialog() {
  const [url, setUrl] = useState("");
  const [open, setOpen] = useState(false);
  const { launch } = useLaunchRun();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm">
            + Add URL
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add job by URL</DialogTitle>
        </DialogHeader>
        <Label htmlFor="add-url">Job posting URL</Label>
        <Input
          id="add-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
        />
        <Button
          disabled={!url.trim()}
          onClick={async () => {
            await launch("addJobUrl", () =>
              unwrap(api.POST("/api/jobs/from-url", { body: { url, allowBrowser: true } })),
            );
            setOpen(false);
            setUrl("");
          }}
        >
          Add job
        </Button>
      </DialogContent>
    </Dialog>
  );
}
