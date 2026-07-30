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
  const quota = usage.quota;
  const unlimited = isAdmin || quota?.recurringAllowanceMicros == null;
  const percent = unlimited || !quota?.recurringAllowanceMicros
    ? 0
    : Math.min(100, (quota.spendMicros / quota.recurringAllowanceMicros) * 100);
  const money = (micros: number | null | undefined) =>
    micros == null
      ? "Unlimited"
      : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(
          micros / 1_000_000,
        );

  return (
    <Card className="h-full">
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <Gauge aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle>
              <h3>Shared-cost allowance</h3>
            </CardTitle>
            <CardDescription>
              Platform-key cost draws from your recurring allowance, then durable credits.
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge variant={unlimited ? "default" : "outline"}>
            {isAdmin ? "Quota exempt" : quota?.enforcementStatus ?? "Unavailable"}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {unlimited ? (
          <Alert>
            <InfinityIcon aria-hidden="true" />
            <AlertTitle>No usage ceiling</AlertTitle>
            <AlertDescription>
              Administrator usage is recorded for visibility and still counts toward the
              platform cap, but has no user-level allowance ceiling.
            </AlertDescription>
          </Alert>
        ) : (
          <Progress value={percent}>
            <ProgressLabel>Recurring shared-key allowance</ProgressLabel>
            <ProgressValue>
              {() =>
                `${money(quota?.spendMicros)} / ${money(quota?.recurringAllowanceMicros)}`
              }
            </ProgressValue>
          </Progress>
        )}
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg bg-muted/55 p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Remaining balance
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {money(quota?.remainingMicros)}
            </dd>
          </div>
          <div className="rounded-lg bg-muted/55 p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Durable credits
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {money(quota?.creditBalanceMicros)}
            </dd>
          </div>
          <div className="rounded-lg bg-muted/55 p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Shared tokens
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {(usage.sharedTokens?.totalTokens ?? 0).toLocaleString()}
            </dd>
          </div>
          <div className="rounded-lg bg-muted/55 p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              BYOK tokens
            </dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">
              {(usage.byokTokens?.totalTokens ?? 0).toLocaleString()}
            </dd>
          </div>
        </dl>
        {quota ? (
          <p className={`text-xs ${quota.overageMicros > 0 ? "font-medium text-amber-700 dark:text-amber-400" : "text-muted-foreground"}`}>
            {quota.overageMicros > 0 ? `${money(quota.overageMicros)} overage · ` : ""}
            Resets {new Date(quota.nextResetAt).toLocaleString()}.
          </p>
        ) : null}
      </CardContent>
      <CardFooter className="justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          BYOK use is estimated for visibility and never reduces your quota.
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
