import { Download, Gauge, Infinity as InfinityIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import { openDownload } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type AccountUsage = components["schemas"]["AccountUsage"];

export function AccountUsageCard({
  usage,
  isAdmin,
}: {
  usage: AccountUsage;
  isAdmin: boolean;
}) {
  const unlimited = isAdmin || usage.budget === 0;
  const percent = unlimited
    ? 0
    : Math.min(100, (usage.weightedTotal / usage.budget) * 100);

  return (
    <Card className="h-full">
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <Gauge aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle>
              <h3>Weekly usage</h3>
            </CardTitle>
            <CardDescription>
              Shared-provider usage is measured across a rolling seven-day window.
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge variant={unlimited ? "default" : "outline"}>
            {unlimited ? "Unlimited" : "7 days"}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {unlimited ? (
          <Alert>
            <InfinityIcon aria-hidden="true" />
            <AlertTitle>No usage ceiling</AlertTitle>
            <AlertDescription>
              Administrator token usage is recorded for visibility but is never blocked.
            </AlertDescription>
          </Alert>
        ) : (
          <Progress value={percent}>
            <ProgressLabel>Shared token budget</ProgressLabel>
            <ProgressValue>
              {() =>
                `${usage.weightedTotal.toLocaleString()} / ${usage.budget.toLocaleString()}`
              }
            </ProgressValue>
          </Progress>
        )}
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg bg-muted/55 p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Shared weighted tokens
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {usage.weightedTotal.toLocaleString()}
            </dd>
          </div>
          <div className="rounded-lg bg-muted/55 p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Own-key weighted tokens
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {usage.ownKeyWeightedTotal.toLocaleString()}
            </dd>
          </div>
        </dl>
      </CardContent>
      <CardFooter className="justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Own-key calls do not count against shared limits.
        </p>
        <a
          href="/api/account/export"
          className={buttonVariants({ variant: "outline", size: "sm" })}
          onClick={(event) => {
            event.preventDefault();
            void openDownload(event.currentTarget.href);
          }}
        >
          <Download data-icon="inline-start" />
          Export
        </a>
      </CardFooter>
    </Card>
  );
}
