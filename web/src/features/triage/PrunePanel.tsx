import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type PruneReport = components["schemas"]["PruneReportOut"];

export function PrunePanel() {
  const qc = useQueryClient();
  const [fit, setFit] = useState(40);
  const [stale, setStale] = useState(45);
  const [retain, setRetain] = useState(30);

  const body = () => ({
    fitThreshold: fit,
    staleDays: stale,
    retentionDays: retain,
  });

  const preview = useMutation({
    mutationFn: (): Promise<PruneReport> =>
      unwrap(api.POST("/api/prune", { body: { dryRun: true, ...body() } })) as Promise<PruneReport>,
  });
  const run = useMutation({
    mutationFn: (): Promise<PruneReport> =>
      unwrap(
        api.POST("/api/prune", { body: { dryRun: false, ...body() } }),
      ) as Promise<PruneReport>,
    onSettled: () => qc.invalidateQueries({ queryKey: ["triage"] }),
  });

  return (
    <Accordion className="mb-4">
      <AccordionItem value="prune">
        <AccordionTrigger>Prune (archive junk, expire old)</AccordionTrigger>
        <AccordionContent>
          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="p-fit">Fit below</Label>
              <Input
                id="p-fit"
                type="number"
                value={fit}
                onChange={(e) => setFit(Number(e.target.value))}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="p-stale">Stale days</Label>
              <Input
                id="p-stale"
                type="number"
                value={stale}
                onChange={(e) => setStale(Number(e.target.value))}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="p-ret">Retention days</Label>
              <Input
                id="p-ret"
                type="number"
                value={retain}
                onChange={(e) => setRetain(Number(e.target.value))}
              />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Button variant="outline" onClick={() => preview.mutate()}>
              Preview
            </Button>
            <ConfirmDialog
              trigger={<Button>Prune now</Button>}
              title="Run prune?"
              description="Archives junk/low-fit/stale jobs and permanently deletes expired archived jobs. Expiry cannot be undone."
              confirmLabel="Prune now"
              onConfirm={() => run.mutate()}
            />
          </div>
          {preview.data && (
            <p className="mt-2 text-sm text-muted-foreground">
              {preview.data.rejected} rejected · {preview.data.lowFit} low-fit ·{" "}
              {preview.data.stale} stale → {preview.data.archived} archive ·{" "}
              {preview.data.expired} expire · {preview.data.skipped} skipped
            </p>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
