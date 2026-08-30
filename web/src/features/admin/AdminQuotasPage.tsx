import { type ReactNode, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Archive,
  Banknote,
  CircleUserRound,
  Clock3,
  Gauge,
  History,
  Layers3,
  Plus,
  Search,
  Users,
} from "lucide-react";
import { Link, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMe } from "@/features/auth/AuthGate";
import { useModelCatalog } from "@/features/settings/use-model-catalog";
import {
  groupAndSortRates,
  latestVersion,
  RATE_COST_BAND_DETAIL_KEYS,
  RATE_COST_BAND_LABEL_KEYS,
  RATE_COST_BAND_STYLES,
  RATE_SORT_LABEL_KEYS,
  RATE_VERSION_STATUS_LABEL_KEYS,
  rateCostBand,
  rateVersionStatus,
  type LlmRate,
  type RateCostBand,
  type RateSortKey,
  type SortDirection,
} from "@/features/admin/admin-quota-rates";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

type QuotaAccount = components["schemas"]["QuotaAccountOut"];
type QuotaPreview = components["schemas"]["QuotaOperationPreviewOut"];
type QuotaTier = components["schemas"]["QuotaTierOut"];
type QuotaOperationCreate = components["schemas"]["QuotaOperationPreviewCreate"];

type QuotaTargetType = QuotaOperationCreate["targetType"];
type QuotaActionType = QuotaOperationCreate["actionType"];
type CycleUnit = "WEEK" | "MONTH";
type RatePeriodChoice = "all" | "peak" | "off_peak";

const MICROS_PER_USD = 1_000_000;
const CUSTOM_MODEL = "__custom__";
const ALL_BALANCES = "ALL";
const CYCLE_COUNTS = Array.from({ length: 52 }, (_, index) => index + 1);

const TARGET_LABEL_KEYS: Record<QuotaTargetType, string> = {
  USER: "adminQuota.targets.member",
  TIER: "adminQuota.targets.tier",
  ALL_MEMBERS: "adminQuota.targets.allMembers",
};

const ACTION_LABEL_KEYS: Record<QuotaActionType, string> = {
  GRANT_CREDIT: "adminQuota.actions.grantCredit",
  DEBIT_CREDIT: "adminQuota.actions.debitCredit",
  RESET_CURRENT_PERIOD: "adminQuota.actions.resetCurrentPeriod",
};

const RATE_PERIOD_LABEL_KEYS: Record<RatePeriodChoice, string> = {
  all: "adminQuota.rate.periods.all",
  peak: "adminQuota.rate.periods.peak",
  off_peak: "adminQuota.rate.periods.offPeak",
};

const BALANCE_LABEL_KEYS: Record<string, string> = {
  [ALL_BALANCES]: "adminQuota.balances.all",
  POSITIVE: "adminQuota.balances.positive",
  ZERO: "adminQuota.balances.depleted",
  OVERAGE: "adminQuota.balances.overage",
  UNLIMITED: "adminQuota.balances.unlimited",
};

const ACCOUNT_STATUS_LABEL_KEYS: Record<QuotaAccount["status"], string> = {
  ACTIVE: "adminQuota.accountStatuses.active",
  EXHAUSTED: "adminQuota.accountStatuses.exhausted",
  OVERAGE: "adminQuota.accountStatuses.overage",
  UNLIMITED: "adminQuota.accountStatuses.unlimited",
};

const LEDGER_KIND_LABEL_KEYS: Record<string, string> = {
  USAGE: "adminQuota.ledgerKinds.usage",
  CREDIT_GRANT: "adminQuota.ledgerKinds.creditGrant",
  CREDIT_DEBIT: "adminQuota.ledgerKinds.creditDebit",
  RESET: "adminQuota.ledgerKinds.reset",
  TIER_CHANGE: "adminQuota.ledgerKinds.tierChange",
  TIER_ALLOWANCE_CHANGE: "adminQuota.ledgerKinds.tierAllowanceChange",
  OVERRIDE_CHANGE: "adminQuota.ledgerKinds.overrideChange",
};

function quotaActionLabel(t: TFunction, action: string): string {
  const key = ACTION_LABEL_KEYS[action as QuotaActionType];
  return key ? t(key) : action.replaceAll("_", " ");
}

function quotaAccountStatusLabel(t: TFunction, status: QuotaAccount["status"]): string {
  return t(ACCOUNT_STATUS_LABEL_KEYS[status]);
}

function quotaLedgerKindLabel(t: TFunction, kind: string): string {
  const key = LEDGER_KIND_LABEL_KEYS[kind];
  return key ? t(key) : kind.replaceAll("_", " ");
}

function usd(t: TFunction, micros: number | null | undefined): string {
  if (micros == null) return t("adminQuota.values.unlimited");
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(micros / MICROS_PER_USD);
}

function optionalUsd(t: TFunction, micros: number | null | undefined): string {
  return micros == null ? "—" : usd(t, micros);
}

function tokens(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

function optionalMicros(value: string): number | null | undefined {
  if (!value.trim()) return null;
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0) return undefined;
  return Math.round(amount * MICROS_PER_USD);
}

function positiveMicros(value: string): number | undefined {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return undefined;
  return Math.round(amount * MICROS_PER_USD);
}

function usdInputValue(micros: number | null): string {
  return micros == null ? "" : String(micros / MICROS_PER_USD);
}

function tierIdFromName(name: string): string {
  let identifier = name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");

  if (!identifier || !/^[A-Z]/.test(identifier)) identifier = `TIER_${identifier}`;
  if (identifier.length < 2) identifier = `${identifier}_TIER`;
  return identifier.slice(0, 32).replace(/_+$/g, "") || "TIER";
}

function cycleSuffix(t: TFunction, unit: CycleUnit, count: number): string {
  if (unit === "WEEK") {
    return count === 1
      ? t("adminQuota.cycles.everyWeek")
      : t("adminQuota.cycles.everyWeeks", { count });
  }
  return count === 1
    ? t("adminQuota.cycles.everyMonth")
    : t("adminQuota.cycles.everyMonths", { count });
}

/** Agrees with the count beside it, so the pair never reads "Every 1 Months". */
function unitLabel(t: TFunction, unit: CycleUnit, count: string): string {
  if (unit === "WEEK") return t(count === "1" ? "adminQuota.cycles.week" : "adminQuota.cycles.weeks");
  return t(count === "1" ? "adminQuota.cycles.month" : "adminQuota.cycles.months");
}

/**
 * Select triggers ship at `pl-2.5` and `text-sm`; inputs at `px-3` and
 * `text-base md:text-[0.95rem]`. Side by side in a row that difference reads as
 * a misalignment, so every trigger on this page is paired to the input metrics.
 */
const CONTROL_TRIGGER = "w-full pl-3 text-base md:text-[0.95rem]";

/**
 * One label-plus-control geometry for the whole console.
 *
 * Two things break a row of fields, and both are fixed here rather than at each
 * call site. First, `Label` is `leading-none`, so a hand-rolled
 * `<p className="text-sm">` label stands ~6px taller and drops its control out
 * of line. Second, the stack is `flex flex-col gap-1.5` and never `space-y-*`:
 * Tailwind spaces with `:not(:last-child)`, and Base UI's `Select` appends a
 * hidden form input after the trigger, which hands the trigger a stray 6px
 * bottom margin. A flex gap ignores that out-of-flow child.
 */
function Field({
  label,
  htmlFor,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

/** A field-shaped readout for a target the admin cannot change. */
function StaticField({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <span className="flex items-center text-sm leading-none font-medium">{label}</span>
      <div className="flex h-9 items-center rounded-lg border bg-muted/30 px-3 text-base text-muted-foreground md:text-[0.95rem]">
        {children}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  warning = false,
}: {
  label: string;
  value: string;
  detail: string;
  warning?: boolean;
}) {
  return (
    <div className={`border-l-2 px-4 py-2 ${warning ? "border-amber-500" : "border-primary/50"}`}>
      <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1">
        <span className="block font-mono text-2xl font-semibold tabular-nums">{value}</span>
        <span className="mt-1 block text-xs text-muted-foreground">{detail}</span>
      </dd>
    </div>
  );
}

function SortableRateHead({
  sortKey,
  activeKey,
  direction,
  onSort,
}: {
  sortKey: RateSortKey;
  activeKey: RateSortKey;
  direction: SortDirection;
  onSort: (key: RateSortKey) => void;
}) {
  const { t } = useTranslation();
  const active = activeKey === sortKey;
  const Icon = active ? (direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;

  return (
    <TableHead aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        className="-mx-1 inline-flex h-8 items-center gap-1 rounded-md px-1 text-left hover:text-primary focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        onClick={() => onSort(sortKey)}
      >
        {t(RATE_SORT_LABEL_KEYS[sortKey])}
        <Icon className={cn("size-3.5", active ? "text-primary" : "text-muted-foreground/60")} aria-hidden="true" />
      </button>
    </TableHead>
  );
}

function RateVersionsTable({ rates }: { rates: LlmRate[] }) {
  const { t } = useTranslation();
  const [sortKey, setSortKey] = useState<RateSortKey>("effective");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const groups = useMemo(
    () => groupAndSortRates(rates, sortKey, direction),
    [direction, rates, sortKey],
  );

  const onSort = (nextKey: RateSortKey) => {
    if (nextKey === sortKey) {
      setDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setDirection(nextKey === "effective" ? "desc" : "asc");
  };

  return (
    <Table containerClassName="overflow-visible" className="min-w-[1120px]" aria-label="Effective rate versions">
      <TableHeader className="sticky top-0 z-[1] bg-card shadow-[0_1px_0_hsl(var(--border))]">
        <TableRow>
          <SortableRateHead sortKey="model" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="context" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="input" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="cache" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="output" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="tool" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="hours" activeKey={sortKey} direction={direction} onSort={onSort} />
          <SortableRateHead sortKey="effective" activeKey={sortKey} direction={direction} onSort={onSort} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {groups.flatMap((group) => group.versions.map((rate, versionIndex) => {
          const band = rateCostBand(latestVersion(group));
          const tone = RATE_COST_BAND_STYLES[band];
          const status = rateVersionStatus(rate);
          return (
            <TableRow
              key={rate.id}
              data-model={group.model}
              data-effective-from={rate.effectiveFrom}
              className={cn(versionIndex === 0 && "border-t-2 border-t-border", versionIndex > 0 && "bg-muted/[0.16]")}
            >
              {versionIndex === 0 ? (
                <TableCell rowSpan={group.versions.length} data-rate-cost-band={band} className="relative min-w-56 border-r align-top pl-5">
                  <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-1", tone.rail)} />
                  <div className="font-mono text-sm font-semibold">{group.model}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs capitalize text-muted-foreground">{group.provider}</span>
                    <Badge variant="outline" className={cn("h-5 px-1.5 text-[0.65rem]", tone.badge)}>{t(RATE_COST_BAND_LABEL_KEYS[band])}</Badge>
                  </div>
                  {group.versions.length > 1 ? (
                    <div className="mt-2 text-[0.68rem] text-muted-foreground">{group.versions.length} versions · newest first</div>
                  ) : null}
                </TableCell>
              ) : null}
              <TableCell className="font-mono">{tokens(rate.contextMinTokens)}–{rate.contextMaxTokens == null ? "∞" : tokens(rate.contextMaxTokens)}</TableCell>
              <TableCell className="font-mono tabular-nums">{usd(t, rate.inputMicrosPerMillion)}</TableCell>
              <TableCell className="font-mono tabular-nums">{optionalUsd(t, rate.cacheReadMicrosPerMillion)} / {optionalUsd(t, rate.cacheWriteMicrosPerMillion)}</TableCell>
              <TableCell className="font-mono tabular-nums">{usd(t, rate.outputMicrosPerMillion)}</TableCell>
              <TableCell className="font-mono tabular-nums">{optionalUsd(t, rate.toolMicrosPerUnit)}</TableCell>
              <TableCell>{t(RATE_PERIOD_LABEL_KEYS[rate.ratePeriod ?? "all"])}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <span className="font-mono">{new Date(rate.effectiveFrom).toLocaleDateString()}</span>
                  <Badge variant="outline" className="h-5 px-1.5 text-[0.65rem]">{t(RATE_VERSION_STATUS_LABEL_KEYS[status])}</Badge>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {rate.effectiveTo
                    ? t("adminQuota.rate.effectiveUntil", { date: new Date(rate.effectiveTo).toLocaleDateString() })
                    : t("adminQuota.rate.noEndDate")}
                </div>
              </TableCell>
            </TableRow>
          );
        }))}
      </TableBody>
    </Table>
  );
}

function AccountDrawer({
  account,
  tiers,
  open,
  onOpenChange,
}: {
  account: QuotaAccount | null;
  tiers: QuotaTier[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tierId, setTierId] = useState("");
  const [override, setOverride] = useState("");
  const [clearOverride, setClearOverride] = useState(false);
  const [reason, setReason] = useState("");
  const ledger = useQuery({
    queryKey: ["admin", "quota-ledger", account?.userId],
    enabled: account != null,
    queryFn: () => unwrap(api.GET("/api/admin/quota-accounts/{user_id}/ledger", {
      params: { path: { user_id: account!.userId }, query: { page_size: 20 } },
    })),
  });
  const patch = useMutation({
    mutationFn: () => {
      if (!account) throw new Error("No member selected");
      const body: {
        tierId?: string;
        allowanceOverrideMicros?: number | null;
        reason: string;
      } = { reason };
      if (tierId) body.tierId = tierId;
      if (clearOverride) body.allowanceOverrideMicros = null;
      else if (override !== "") body.allowanceOverrideMicros = Math.round(Number(override) * MICROS_PER_USD);
      return unwrap(api.PATCH("/api/admin/quota-accounts/{user_id}", {
        params: { path: { user_id: account.userId } },
        body,
      }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
      setTierId("");
      setOverride("");
      setClearOverride(false);
      setReason("");
      onOpenChange(false);
    },
  });
  const overrideIsValid = override === "" || optionalMicros(override) !== undefined;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader className="border-b p-6">
          <SheetTitle>{account?.username ?? "Member quota"}</SheetTitle>
          <SheetDescription>
            Assign a plan or set a persistent allowance override. Every saved change is audited.
          </SheetDescription>
        </SheetHeader>
        {account ? (
          <div className="space-y-5 p-6">
            <dl className="grid grid-cols-2 gap-4 rounded-lg border bg-muted/15 p-4 text-sm">
              <div>
                <dt className="text-muted-foreground">Tier</dt>
                <dd className="mt-1 font-mono">{account.tierId}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd className="mt-1">
                  <Badge variant={account.status === "OVERAGE" ? "destructive" : "outline"}>
                    {quotaAccountStatusLabel(t, account.status)}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Period spend</dt>
                <dd className="mt-1 font-mono">{usd(t, account.spentMicros)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Credits</dt>
                <dd className="mt-1 font-mono">{usd(t, account.creditBalanceMicros)}</dd>
              </div>
            </dl>

            <Field label="Assign tier" htmlFor="drawer-tier">
              <Select value={tierId} onValueChange={(value) => setTierId(value ?? "")}>
                <SelectTrigger id="drawer-tier" size="compact" className={CONTROL_TRIGGER} aria-label="Assign member tier">
                  <SelectValue>
                    {(value) =>
                      tiers.find((tier) => tier.id === value)?.name ?? `Keep ${account.tierId}`}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {tiers.map((tier) => (
                    <SelectItem key={tier.id} value={tier.id}>
                      {tier.name} · {tier.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <div className="space-y-3 rounded-lg border p-4">
              <div className="space-y-1">
                <Label htmlFor="drawer-override">Allowance override (USD)</Label>
                <p className="text-xs text-muted-foreground">
                  Leave blank to preserve the current override.
                </p>
              </div>
              <Input
                id="drawer-override"
                className="h-9"
                aria-invalid={!overrideIsValid}
                inputMode="decimal"
                disabled={clearOverride}
                placeholder="e.g. 25.00"
                value={override}
                onChange={(event) => setOverride(event.target.value)}
              />
              <div className="flex items-start gap-3">
                <Switch
                  id="clear-override"
                  checked={clearOverride}
                  onCheckedChange={setClearOverride}
                />
                <div>
                  <Label htmlFor="clear-override">Return to tier allowance</Label>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Clear the override and inherit the selected tier’s allowance.
                  </p>
                </div>
              </div>
            </div>

            <Field label="Reason for this member change" htmlFor="drawer-reason">
              <Input
                id="drawer-reason"
                className="h-9"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why is this member change needed?"
              />
            </Field>
            {patch.isError ? (
              <Alert variant="destructive">
                <AlertTitle>Update failed</AlertTitle>
                <AlertDescription>{patch.error.message}</AlertDescription>
              </Alert>
            ) : null}
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={
                  !reason.trim()
                  || (!tierId && override === "" && !clearOverride)
                  || !overrideIsValid
                  || patch.isPending
                }
                onClick={() => patch.mutate()}
              >
                {patch.isPending ? "Saving…" : "Save member change"}
              </Button>
            </div>

            <section aria-labelledby="member-ledger" className="space-y-3 border-t pt-5">
              <h3 id="member-ledger" className="font-semibold">Recent ledger</h3>
              {ledger.isPending ? <Skeleton className="h-24 w-full" /> : null}
              {!ledger.isPending && ledger.data?.data.length ? (
                <ul className="space-y-2">
                  {ledger.data.data.map((entry) => (
                    <li key={entry.id} className="rounded-lg border p-3 text-xs">
                      <div className="flex justify-between gap-3">
                        <span className="font-medium">{quotaLedgerKindLabel(t, entry.kind)}</span>
                        <span className="font-mono">{usd(t, entry.amountMicros)}</span>
                      </div>
                      <div className="mt-1 text-muted-foreground">
                        {entry.reason ?? "Automated usage accounting"} · {new Date(entry.createdAt).toLocaleString()}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : null}
              {!ledger.isPending && !ledger.data?.data.length ? (
                <p className="text-sm text-muted-foreground">No quota ledger entries yet.</p>
              ) : null}
            </section>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function QuotaOperationCard({
  accounts,
  tiers,
  targetTypes,
  title,
  description,
}: {
  accounts: QuotaAccount[];
  tiers: QuotaTier[];
  targetTypes: QuotaTargetType[];
  title: string;
  description: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [targetType, setTargetType] = useState<QuotaTargetType>(targetTypes[0]);
  const [targetValue, setTargetValue] = useState("");
  const [actionType, setActionType] = useState<QuotaActionType>("GRANT_CREDIT");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<QuotaPreview | null>(null);
  const amountMicros = positiveMicros(amount);
  const requiresAmount = actionType !== "RESET_CURRENT_PERIOD";
  const targetIsSelected = targetType === "ALL_MEMBERS" || Boolean(targetValue);

  const clearPreview = () => setPreview(null);
  const previewMutation = useMutation({
    mutationFn: () => {
      if (!targetIsSelected) throw new Error("Select a target before previewing the operation");
      if (requiresAmount && amountMicros == null) throw new Error("Enter a positive USD amount");
      const body = {
        targetType,
        ...(targetType === "ALL_MEMBERS" ? {} : { targetValue }),
        actionType,
        amountMicros: requiresAmount ? amountMicros! : null,
      };
      return unwrap(api.POST("/api/admin/quota-operation-previews", { body }));
    },
    onSuccess: setPreview,
  });
  const commit = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("Preview required");
      return unwrap(api.POST("/api/admin/quota-operations", {
        body: {
          previewId: preview.id,
          reason,
          idempotencyKey: crypto.randomUUID(),
        },
      }));
    },
    onSuccess: () => {
      setPreview(null);
      setReason("");
      setAmount("");
      setTargetValue("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-operations"] });
    },
  });

  function changeTargetType(value: QuotaTargetType) {
    setTargetType(value);
    setTargetValue("");
    clearPreview();
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>
          <h2 className="flex items-center gap-2 text-base">
            <Banknote className="size-4 text-muted-foreground" aria-hidden="true" />
            {title}
          </h2>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          {targetTypes.length > 1 ? (
            <Field label="Scope" htmlFor={`${title}-scope`} className="w-36">
              <Select value={targetType} onValueChange={(value) => changeTargetType(value as QuotaTargetType)}>
                <SelectTrigger id={`${title}-scope`} size="compact" className={CONTROL_TRIGGER} aria-label="Target scope">
                  <SelectValue>{(value) => t(TARGET_LABEL_KEYS[value as QuotaTargetType])}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {targetTypes.map((type) => (
                    <SelectItem key={type} value={type}>{t(TARGET_LABEL_KEYS[type])}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          ) : null}

          {targetType === "USER" ? (
            <Field label="Member" htmlFor={`${title}-member`} className="w-48">
              <Select
                value={targetValue}
                onValueChange={(value) => {
                  setTargetValue(value ?? "");
                  clearPreview();
                }}
              >
                <SelectTrigger id={`${title}-member`} size="compact" className={CONTROL_TRIGGER} aria-label="Target member">
                  <SelectValue>
                    {(value) =>
                      accounts.find((account) => account.userId === value)?.username ?? "Choose a member"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {accounts.map((account) => (
                    <SelectItem key={account.userId} value={account.userId}>
                      {account.username} · {account.tierId}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          ) : null}

          {targetType === "TIER" ? (
            <Field label="Tier" htmlFor={`${title}-tier`} className="w-48">
              <Select
                value={targetValue}
                onValueChange={(value) => {
                  setTargetValue(value ?? "");
                  clearPreview();
                }}
              >
                <SelectTrigger id={`${title}-tier`} size="compact" className={CONTROL_TRIGGER} aria-label="Target tier">
                  <SelectValue>
                    {(value) => tiers.find((tier) => tier.id === value)?.name ?? "Choose a tier"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {tiers.map((tier) => (
                    <SelectItem key={tier.id} value={tier.id}>
                      {tier.name} · {tier.memberCount} members
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          ) : null}

          {targetType === "ALL_MEMBERS" ? (
            <StaticField label="Target" className="w-48">
              All {accounts.length} member accounts
            </StaticField>
          ) : null}

          <Field label="Action" htmlFor={`${title}-action`} className="w-40">
            <Select
              value={actionType}
              onValueChange={(value) => {
                setActionType(value as QuotaActionType);
                clearPreview();
              }}
            >
              <SelectTrigger id={`${title}-action`} size="compact" className={CONTROL_TRIGGER} aria-label="Quota action">
                  <SelectValue>{(value) => t(ACTION_LABEL_KEYS[value as QuotaActionType])}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ACTION_LABEL_KEYS) as QuotaActionType[]).map((action) => (
                  <SelectItem key={action} value={action}>{t(ACTION_LABEL_KEYS[action])}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          {requiresAmount ? (
            <Field label="Amount (USD)" htmlFor={`${title}-amount`} className="w-32">
              <Input
                id={`${title}-amount`}
                className="h-9"
                aria-invalid={amount !== "" && amountMicros == null}
                inputMode="decimal"
                placeholder="10.00"
                value={amount}
                onChange={(event) => {
                  setAmount(event.target.value);
                  clearPreview();
                }}
              />
            </Field>
          ) : null}

          <Field label="Reason for this operation" htmlFor={`${title}-reason`} className="min-w-48 flex-1">
            <Input
              id={`${title}-reason`}
              className="h-9"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why this operation is needed"
            />
          </Field>

          <Button
            size="sm"
            variant="outline"
            disabled={!targetIsSelected || (requiresAmount && amountMicros == null) || previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
          >
            {previewMutation.isPending ? "Preparing…" : "Preview impact"}
          </Button>
        </div>

        {preview ? (
          <div className="flex flex-col gap-3 rounded-lg border border-amber-500/40 bg-amber-500/[0.04] p-3 duration-150 ease-out-strong animate-in fade-in-0 slide-in-from-top-1 motion-reduce:animate-none sm:flex-row sm:items-center">
            <AlertTriangle className="size-5 shrink-0 text-amber-600" aria-hidden="true" />
            <div className="flex-1">
              <div className="text-sm font-medium">
                {`${preview.affectedCount} account${preview.affectedCount === 1 ? "" : "s"} frozen for review`}
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                Total effect {usd(t, preview.totalEffectMicros)} · preview expires {new Date(preview.expiresAt).toLocaleTimeString()}
              </div>
            </div>
            <Button
              size="sm"
              variant={actionType === "DEBIT_CREDIT" || actionType === "RESET_CURRENT_PERIOD" ? "destructive" : "default"}
              disabled={!reason.trim() || commit.isPending}
              onClick={() => commit.mutate()}
            >
              {commit.isPending ? "Applying…" : "Confirm operation"}
            </Button>
          </div>
        ) : null}

        {previewMutation.isError || commit.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Quota operation failed</AlertTitle>
            <AlertDescription>{previewMutation.error?.message ?? commit.error?.message}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}

const TIER_ID_PATTERN = /^[A-Z][A-Z0-9_]{1,31}$/;

/** Roster geometry. The header, every tier row, and the editor all read from it. */
const TIER_GRID = "grid grid-cols-[minmax(9rem,1fr)_7rem_9rem_5rem_7rem_4.5rem] items-center gap-3";

type TierForm = {
  id: string;
  name: string;
  allowance: string;
  cycleUnit: CycleUnit;
  cycleCount: string;
  reason: string;
};

function formFromTier(tier: QuotaTier): TierForm {
  return {
    id: tier.id,
    name: tier.name,
    allowance: usdInputValue(tier.allowanceMicros),
    cycleUnit: tier.cycleUnit,
    cycleCount: String(tier.cycleCount),
    reason: "",
  };
}

const BLANK_TIER_FORM: TierForm = {
  id: "",
  name: "",
  allowance: "",
  cycleUnit: "MONTH",
  cycleCount: "1",
  reason: "",
};

function TierColumnHeader() {
  return (
    <div
      className={cn(
        TIER_GRID,
        "border-b bg-muted/25 px-4 py-2 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground",
      )}
    >
      <span>Tier</span>
      <span>Short ID</span>
      <span>Allowance</span>
      <span className="text-right">Members</span>
      <span className="text-right">Spend</span>
      <span className="sr-only">Actions</span>
    </div>
  );
}

/**
 * The create and edit forms are the same component so a tier is configured with
 * the same controls that made it. Only the immutable short ID differs: it is an
 * input at creation and a fixed readout afterwards.
 */
function TierEditor({
  form,
  onChange,
  mode,
  tier,
  onCancel,
  onSubmit,
  onArchive,
  isSaving,
  isArchiving,
  error,
}: {
  form: TierForm;
  onChange: (changes: Partial<TierForm>) => void;
  mode: "create" | "edit";
  tier: QuotaTier | null;
  onCancel: () => void;
  onSubmit: () => void;
  onArchive: () => void;
  isSaving: boolean;
  isArchiving: boolean;
  error: string | null;
}) {
  const { t } = useTranslation();
  const prefix = mode === "create" ? "new-tier" : "edit-tier";
  const allowanceMicros = optionalMicros(form.allowance);
  const allowanceIsValid = allowanceMicros !== undefined;
  const idIsValid = TIER_ID_PATTERN.test(form.id);
  const hasReason = Boolean(form.reason.trim());
  const changed = tier
    ? form.name.trim() !== tier.name
      || form.cycleUnit !== tier.cycleUnit
      || Number(form.cycleCount) !== tier.cycleCount
      || allowanceMicros !== tier.allowanceMicros
    : true;
  const canSubmit = Boolean(
    form.name.trim() && allowanceIsValid && hasReason && changed && (mode === "edit" || idIsValid),
  );

  return (
    <div className="border-t bg-muted/20 px-4 py-4 duration-150 ease-out-strong animate-in fade-in-0 slide-in-from-top-1 motion-reduce:animate-none">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Tier name" htmlFor={`${prefix}-name`} className="w-48">
          <Input
            id={`${prefix}-name`}
            className="h-9"
            placeholder="e.g. Team"
            value={form.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </Field>

        {mode === "create" ? (
          <Field label="Short ID" htmlFor="new-tier-id" className="w-48">
            <Input
              id="new-tier-id"
              className="h-9 font-mono uppercase"
              aria-invalid={form.id !== "" && !idIsValid}
              aria-describedby="new-tier-id-rule"
              placeholder="TEAM"
              value={form.id}
              onChange={(event) => onChange({ id: event.target.value.toUpperCase() })}
            />
          </Field>
        ) : (
          <StaticField label="Short ID" className="w-48">
            <span className="font-mono">{form.id}</span>
          </StaticField>
        )}

        <Field label="Allowance (USD)" htmlFor={`${prefix}-allowance`} className="w-36">
          <Input
            id={`${prefix}-allowance`}
            className="h-9"
            aria-invalid={form.allowance !== "" && !allowanceIsValid}
            inputMode="decimal"
            placeholder="Unlimited"
            value={form.allowance}
            onChange={(event) => onChange({ allowance: event.target.value })}
          />
        </Field>

        <Field label="Every" htmlFor={`${prefix}-count`} className="w-20">
          <Select
            value={form.cycleCount}
            onValueChange={(value) => onChange({ cycleCount: value ?? "1" })}
          >
            <SelectTrigger
              id={`${prefix}-count`}
              size="compact"
              className={CONTROL_TRIGGER}
              aria-label={mode === "create" ? "New tier cycle count" : "Tier cycle count"}
            >
              <SelectValue>{(value) => String(value ?? "1")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {CYCLE_COUNTS.map((count) => <SelectItem key={count} value={String(count)}>{count}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Period" htmlFor={`${prefix}-unit`} className="w-32">
          <Select
            value={form.cycleUnit}
            onValueChange={(value) => onChange({ cycleUnit: value as CycleUnit })}
          >
            <SelectTrigger
              id={`${prefix}-unit`}
              size="compact"
              className={CONTROL_TRIGGER}
              aria-label={mode === "create" ? "New tier cycle period" : "Tier cycle period"}
            >
              <SelectValue>{(value) => unitLabel(t, value as CycleUnit, form.cycleCount)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="MONTH">{unitLabel(t, "MONTH", form.cycleCount)}</SelectItem>
              <SelectItem value="WEEK">{unitLabel(t, "WEEK", form.cycleCount)}</SelectItem>
            </SelectContent>
          </Select>
        </Field>

        <Field
          label={mode === "create" ? "Reason for this new tier" : "Reason for this tier change"}
          htmlFor={`${prefix}-reason`}
          className="min-w-48 flex-1"
        >
          <Input
            id={`${prefix}-reason`}
            className="h-9"
            value={form.reason}
            onChange={(event) => onChange({ reason: event.target.value })}
            placeholder={mode === "create" ? "Why this tier is being added" : "Why this tier is changing"}
          />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p id="new-tier-id-rule" className="text-xs text-muted-foreground">
          {mode === "create"
            ? "The short ID is permanent. Use A–Z, 0–9 and underscores, starting with a letter."
            : `${tier?.memberCount ?? 0} member${tier?.memberCount === 1 ? "" : "s"} on this tier · ${usd(t, tier?.spendMicros ?? 0)} spent this period`}
        </p>
        <div className="flex gap-2">
          {mode === "edit" && tier && !tier.isDefault ? (
            <Button
              size="sm"
              variant="destructive"
              disabled={!hasReason || isArchiving}
              onClick={onArchive}
            >
              <Archive data-icon="inline-start" />
              {isArchiving ? "Archiving…" : "Archive tier"}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button size="sm" disabled={!canSubmit || isSaving} onClick={onSubmit}>
            {isSaving
              ? (mode === "create" ? "Creating…" : "Saving…")
              : (mode === "create" ? "Create tier" : "Save changes")}
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertTitle>{mode === "create" ? "Tier not created" : "Tier not updated"}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

function TierPanel({ tiers, accounts }: { tiers: QuotaTier[]; accounts: QuotaAccount[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<TierForm>(BLANK_TIER_FORM);
  // The short ID follows the name until an admin types their own.
  const [idIsCustom, setIdIsCustom] = useState(false);

  const editingTier = tiers.find((tier) => tier.id === editingId) ?? null;

  function updateForm(changes: Partial<TierForm>) {
    if (changes.id !== undefined) setIdIsCustom(true);
    setForm((current) => {
      const next = { ...current, ...changes };
      if (creating && changes.name !== undefined && changes.id === undefined && !idIsCustom) {
        next.id = changes.name.trim() ? tierIdFromName(changes.name) : "";
      }
      return next;
    });
  }

  function closeEditor() {
    setCreating(false);
    setEditingId(null);
    setIdIsCustom(false);
    create.reset();
    save.reset();
    archive.reset();
  }

  function startCreate() {
    setEditingId(null);
    setIdIsCustom(false);
    setForm(BLANK_TIER_FORM);
    setCreating(true);
    create.reset();
  }

  function startEdit(tier: QuotaTier) {
    setCreating(false);
    setIdIsCustom(false);
    setForm(formFromTier(tier));
    setEditingId(tier.id);
    save.reset();
    archive.reset();
  }

  function tierPatch(tier: QuotaTier) {
    const allowanceMicros = optionalMicros(form.allowance);
    const body: {
      name?: string;
      cycleUnit?: CycleUnit;
      cycleCount?: number;
      allowanceMicros?: number | null;
      reason: string;
    } = { reason: form.reason };
    if (form.name.trim() !== tier.name) body.name = form.name.trim();
    if (form.cycleUnit !== tier.cycleUnit) body.cycleUnit = form.cycleUnit;
    if (Number(form.cycleCount) !== tier.cycleCount) body.cycleCount = Number(form.cycleCount);
    if (allowanceMicros !== tier.allowanceMicros) body.allowanceMicros = allowanceMicros;
    return body;
  }

  function refreshTiers() {
    void queryClient.invalidateQueries({ queryKey: ["admin", "quota-tiers"] });
    void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
  }

  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/quota-tiers", {
      body: {
        id: form.id,
        name: form.name.trim(),
        cycleUnit: form.cycleUnit,
        cycleCount: Number(form.cycleCount),
        allowanceMicros: optionalMicros(form.allowance) ?? null,
        reason: form.reason,
      },
    })),
    onSuccess: () => {
      setCreating(false);
      setIdIsCustom(false);
      setForm(BLANK_TIER_FORM);
      refreshTiers();
    },
  });
  const save = useMutation({
    mutationFn: () => {
      if (!editingTier) throw new Error("No tier changes to save");
      return unwrap(api.PATCH("/api/admin/quota-tiers/{tier_id}", {
        params: { path: { tier_id: editingTier.id } },
        body: tierPatch(editingTier),
      }));
    },
    onSuccess: () => {
      setEditingId(null);
      refreshTiers();
    },
  });
  const archive = useMutation({
    mutationFn: () => {
      if (!editingTier) throw new Error("No tier selected");
      return unwrap(api.PATCH("/api/admin/quota-tiers/{tier_id}", {
        params: { path: { tier_id: editingTier.id } },
        body: { archived: true, reason: form.reason },
      }));
    },
    onSuccess: () => {
      setEditingId(null);
      refreshTiers();
    },
  });

  return (
    <div className="space-y-5 pt-4">
      <Card className="gap-0 overflow-hidden py-0">
        <CardHeader className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-4">
          <div>
            <CardTitle>
              <h2 className="flex items-center gap-2 text-base">
                <Layers3 className="size-4 text-muted-foreground" aria-hidden="true" />
                Allowance tiers
              </h2>
            </CardTitle>
            <CardDescription className="mt-1">
              Each tier grants a recurring allowance to every member assigned to it. Edit a tier in place; changes are audited.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" disabled={creating} onClick={startCreate}>
            <Plus data-icon="inline-start" />
            New tier
          </Button>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <div className="min-w-[46rem]">
            <TierColumnHeader />
            {creating ? (
              <TierEditor
                form={form}
                onChange={updateForm}
                mode="create"
                tier={null}
                onCancel={closeEditor}
                onSubmit={() => create.mutate()}
                onArchive={() => undefined}
                isSaving={create.isPending}
                isArchiving={false}
                error={create.error?.message ?? null}
              />
            ) : null}
            {tiers.map((tier) => (
              <div
                key={tier.id}
                className={cn(
                  "border-b last:border-b-0",
                  editingId === tier.id ? "bg-muted/10" : undefined,
                )}
              >
                <div className={cn(TIER_GRID, "px-4 py-3")}>
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-medium">{tier.name}</span>
                    {tier.isDefault ? (
                      <Badge variant="secondary" className="shrink-0">Default</Badge>
                    ) : null}
                  </div>
                  <span className="truncate font-mono text-xs text-muted-foreground">{tier.id}</span>
                  <div className="min-w-0">
                    <div className="truncate font-mono text-sm tabular-nums">{usd(t, tier.allowanceMicros)}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {cycleSuffix(t, tier.cycleUnit, tier.cycleCount)}
                    </div>
                  </div>
                  <span className="text-right font-mono text-sm tabular-nums">{tier.memberCount}</span>
                  <span className="text-right font-mono text-sm tabular-nums">{usd(t, tier.spendMicros)}</span>
                  <Button
                    size="xs"
                    variant="ghost"
                    className="justify-self-end"
                    aria-expanded={editingId === tier.id}
                    aria-label={`${editingId === tier.id ? "Close" : "Edit"} ${tier.name} tier`}
                    onClick={() => (editingId === tier.id ? closeEditor() : startEdit(tier))}
                  >
                    {editingId === tier.id ? "Close" : "Edit"}
                  </Button>
                </div>
                {editingId === tier.id ? (
                  <TierEditor
                    form={form}
                    onChange={updateForm}
                    mode="edit"
                    tier={tier}
                    onCancel={closeEditor}
                    onSubmit={() => save.mutate()}
                    onArchive={() => archive.mutate()}
                    isSaving={save.isPending}
                    isArchiving={archive.isPending}
                    error={save.error?.message ?? archive.error?.message ?? null}
                  />
                ) : null}
              </div>
            ))}
            {tiers.length === 0 && !creating ? (
              <div className="px-4 py-12 text-center">
                <p className="font-medium">No allowance tiers yet</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Create a tier to start granting members a recurring allowance.
                </p>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <QuotaOperationCard
        accounts={accounts}
        tiers={tiers}
        targetTypes={["TIER"]}
        title="Tier balance operation"
        description="Apply one audited credit or period action to every member currently on a tier."
      />
    </div>
  );
}

function RateCreator({ rates }: { rates: LlmRate[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const modelCatalog = useModelCatalog();
  const [providerChoice, setProviderChoice] = useState<string | null>(null);
  const [modelChoice, setModelChoice] = useState(CUSTOM_MODEL);
  const [customModel, setCustomModel] = useState("");
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [effective, setEffective] = useState("");
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [ratePeriod, setRatePeriod] = useState<RatePeriodChoice>("all");
  const [showOptionalRates, setShowOptionalRates] = useState(false);
  const [cacheRead, setCacheRead] = useState("");
  const [cacheWrite, setCacheWrite] = useState("");
  const [toolFee, setToolFee] = useState("");

  const providers = useMemo(() => {
    if (modelCatalog.data?.length) {
      return modelCatalog.data.map(({ provider, label }) => ({ provider, label }));
    }
    return Array.from(new Set(rates.map((rate) => rate.provider)))
      .sort()
      .map((provider) => ({ provider, label: provider }));
  }, [modelCatalog.data, rates]);
  const provider = providerChoice ?? providers[0]?.provider ?? "";
  const models = useMemo(
    () => Array.from(new Set(rates.filter((rate) => rate.provider === provider).map((rate) => rate.model))).sort(),
    [provider, rates],
  );
  const model = modelChoice === CUSTOM_MODEL ? customModel.trim() : modelChoice;
  const inputMicros = positiveMicros(input);
  const outputMicros = positiveMicros(output);
  const cacheReadMicros = optionalMicros(cacheRead);
  const cacheWriteMicros = optionalMicros(cacheWrite);
  const toolFeeMicros = optionalMicros(toolFee);
  const effectiveDate = effective ? new Date(effective) : null;
  const effectiveIsValid = effectiveDate != null && !Number.isNaN(effectiveDate.getTime());
  const optionalRatesAreValid = [cacheReadMicros, cacheWriteMicros, toolFeeMicros].every((value) => value !== undefined);
  const canCreate = Boolean(
    model
    && inputMicros != null
    && outputMicros != null
    && effectiveIsValid
    && source.trim()
    && reason.trim()
    && optionalRatesAreValid,
  );

  function changeProvider(value: string) {
    setProviderChoice(value);
    const nextModels = Array.from(new Set(rates.filter((rate) => rate.provider === value).map((rate) => rate.model)));
    setModelChoice(nextModels[0] ?? CUSTOM_MODEL);
    setCustomModel("");
    setRatePeriod(value === "deepseek" ? ratePeriod : "all");
  }

  const create = useMutation({
    mutationFn: () => {
      if (!effectiveDate || inputMicros == null || outputMicros == null) {
        throw new Error("Complete the required rate fields");
      }
      return unwrap(api.POST("/api/admin/llm-rates", {
        body: {
          provider,
          model,
          contextMinTokens: 0,
          contextMaxTokens: null,
          inputMicrosPerMillion: inputMicros,
          cacheReadMicrosPerMillion: cacheReadMicros ?? null,
          cacheWriteMicrosPerMillion: cacheWriteMicros ?? null,
          outputMicrosPerMillion: outputMicros,
          toolMicrosPerUnit: toolFeeMicros ?? null,
          ratePeriod: ratePeriod === "all" ? null : ratePeriod,
          effectiveFrom: effectiveDate.toISOString(),
          effectiveTo: null,
          sourceUrl: source.trim(),
          reason,
        },
      }));
    },
    onSuccess: () => {
      setModelChoice(CUSTOM_MODEL);
      setCustomModel("");
      setInput("");
      setOutput("");
      setEffective("");
      setSource("");
      setReason("");
      setRatePeriod("all");
      setShowOptionalRates(false);
      setCacheRead("");
      setCacheWrite("");
      setToolFee("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-rates"] });
    },
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle><h2 className="text-base">Create future rate version</h2></CardTitle>
        <CardDescription>
          Start with the provider and model already billed by the app. Historical rows remain immutable.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Provider" htmlFor="rate-provider" className="w-full sm:w-40">
            <Select value={provider} onValueChange={(value) => changeProvider(value ?? "")}>
              <SelectTrigger id="rate-provider" size="compact" className={CONTROL_TRIGGER} aria-label="Rate provider"><SelectValue>{(value) => String(value ?? "")}</SelectValue></SelectTrigger>
              <SelectContent>
                {providers.map((item) => <SelectItem key={item.provider} value={item.provider}>{item.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Model" htmlFor="rate-model" className="w-full sm:w-64">
            <Select value={modelChoice} onValueChange={(value) => setModelChoice(value ?? CUSTOM_MODEL)}>
              <SelectTrigger id="rate-model" size="compact" className={CONTROL_TRIGGER} aria-label="Rate model"><SelectValue>{(value) => (value === CUSTOM_MODEL ? "Another model identifier" : String(value ?? ""))}</SelectValue></SelectTrigger>
              <SelectContent>
                {models.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
                <SelectItem value={CUSTOM_MODEL}>Another model identifier</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {modelChoice === CUSTOM_MODEL ? (
            <Field label="Model identifier" htmlFor="custom-rate-model" className="min-w-0 flex-1 sm:min-w-56">
              <Input id="custom-rate-model" className="h-9" placeholder="model-id" value={customModel} onChange={(event) => setCustomModel(event.target.value)} />
            </Field>
          ) : null}
          <Field label="Input (USD / 1M)" htmlFor="rate-input" className="w-full sm:w-40">
            <Input id="rate-input" className="h-9" aria-invalid={input !== "" && inputMicros == null} inputMode="decimal" placeholder="e.g. 3.00" value={input} onChange={(event) => setInput(event.target.value)} />
          </Field>
          <Field label="Output (USD / 1M)" htmlFor="rate-output" className="w-full sm:w-40">
            <Input id="rate-output" className="h-9" aria-invalid={output !== "" && outputMicros == null} inputMode="decimal" placeholder="e.g. 15.00" value={output} onChange={(event) => setOutput(event.target.value)} />
          </Field>
          {provider === "deepseek" ? (
            <Field label="Billing hours" htmlFor="rate-period" className="w-full sm:w-40">
              <Select value={ratePeriod} onValueChange={(value) => setRatePeriod(value as RatePeriodChoice)}>
                <SelectTrigger id="rate-period" size="compact" className={CONTROL_TRIGGER} aria-label="Rate billing hours"><SelectValue>{(value) => t(RATE_PERIOD_LABEL_KEYS[value as RatePeriodChoice])}</SelectValue></SelectTrigger>
                <SelectContent>
                  {(Object.keys(RATE_PERIOD_LABEL_KEYS) as RatePeriodChoice[]).map((period) => (
                    <SelectItem key={period} value={period}>{t(RATE_PERIOD_LABEL_KEYS[period])}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          ) : null}
          <Field label="Effective from" htmlFor="rate-effective" className="w-full sm:w-56">
            <Input id="rate-effective" className="h-9" type="datetime-local" value={effective} onChange={(event) => setEffective(event.target.value)} />
          </Field>
          <Field label="Official pricing source" htmlFor="rate-source" className="min-w-0 flex-1 sm:min-w-72">
            <Input id="rate-source" className="h-9" type="url" placeholder="https://…" value={source} onChange={(event) => setSource(event.target.value)} />
          </Field>
        </div>

        <div className="rounded-lg border bg-muted/10 p-3">
          <div
            data-testid="rate-options-row"
            className={cn(
              "grid gap-3 lg:items-end",
              showOptionalRates
                ? "xl:grid-cols-[auto_repeat(3,minmax(6rem,0.4fr))_minmax(8rem,0.7fr)_auto]"
                : "lg:grid-cols-[auto_minmax(0,1fr)_auto]",
            )}
          >
            <div className="flex min-h-9 shrink-0 items-center gap-3 lg:pb-px">
              <Switch id="optional-rate-fields" checked={showOptionalRates} onCheckedChange={setShowOptionalRates} />
              <div>
                <Label htmlFor="optional-rate-fields" className="whitespace-nowrap text-sm font-medium">Optional cache and tool rates</Label>
                <p className="mt-1 whitespace-nowrap text-xs text-muted-foreground">Enable only when the provider charges them.</p>
              </div>
            </div>
            {showOptionalRates ? (
              <>
                <Field label="Cache read (USD / 1M)" htmlFor="rate-cache-read" className="min-w-0"><Input id="rate-cache-read" className="h-9" inputMode="decimal" value={cacheRead} onChange={(event) => setCacheRead(event.target.value)} /></Field>
                <Field label="Cache write (USD / 1M)" htmlFor="rate-cache-write" className="min-w-0"><Input id="rate-cache-write" className="h-9" inputMode="decimal" value={cacheWrite} onChange={(event) => setCacheWrite(event.target.value)} /></Field>
                <Field label="Tool fee (USD / unit)" htmlFor="rate-tool-fee" className="min-w-0"><Input id="rate-tool-fee" className="h-9" inputMode="decimal" value={toolFee} onChange={(event) => setToolFee(event.target.value)} /></Field>
              </>
            ) : null}
            <Field label="Reason for this rate version" htmlFor="rate-reason" className="min-w-0 flex-1">
              <Input id="rate-reason" className="h-9" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why is this pricing version being added?" />
            </Field>
            <Button className="shrink-0" size="sm" disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Creating…" : "Create immutable version"}
            </Button>
          </div>
        </div>
        {create.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Rate version failed</AlertTitle>
            <AlertDescription>{create.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}

function operationTargetLabel(
  t: TFunction,
  operation: components["schemas"]["QuotaOperationOut"],
  accounts: QuotaAccount[],
  tiers: QuotaTier[],
): string {
  if (operation.targetType === "ALL_MEMBERS") return t("adminQuota.targets.allMembers");
  if (operation.targetType === "USER") {
    return accounts.find((account) => account.userId === operation.targetValue)?.username ?? operation.targetValue ?? "Member";
  }
  const tier = tiers.find((item) => item.id === operation.targetValue);
  return tier ? `${tier.name} · ${tier.id}` : operation.targetValue ?? "Tier";
}

export function AdminQuotasPage() {
  const { t } = useTranslation();
  const me = useMe();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<QuotaAccount | null>(null);
  const [balanceFilter, setBalanceFilter] = useState(ALL_BALANCES);
  const summary = useQuery({ queryKey: ["admin", "quota-summary"], queryFn: () => unwrap(api.GET("/api/admin/quota-summary")) });
  const tiers = useQuery({ queryKey: ["admin", "quota-tiers"], queryFn: () => unwrap(api.GET("/api/admin/quota-tiers", { params: { query: { page_size: 100 } } })) });
  const accounts = useQuery({ queryKey: ["admin", "quota-accounts"], queryFn: () => unwrap(api.GET("/api/admin/quota-accounts", { params: { query: { page_size: 100 } } })) });
  const rates = useQuery({ queryKey: ["admin", "llm-rates"], queryFn: () => unwrap(api.GET("/api/admin/llm-rates", { params: { query: { page_size: 100 } } })) });
  const operations = useQuery({ queryKey: ["admin", "quota-operations"], queryFn: () => unwrap(api.GET("/api/admin/quota-operations", { params: { query: { page_size: 100 } } })) });
  const filtered = useMemo(() => (accounts.data?.data ?? []).filter((account) => {
    if (!account.username.toLowerCase().includes(search.toLowerCase())) return false;
    if (balanceFilter === "POSITIVE") return account.remainingMicros != null && account.remainingMicros > 0;
    if (balanceFilter === "ZERO") return account.remainingMicros === 0;
    if (balanceFilter === "OVERAGE") return account.overageMicros > 0;
    if (balanceFilter === "UNLIMITED") return account.remainingMicros == null;
    return true;
  }), [accounts.data, balanceFilter, search]);

  if (me.isPending) return <Skeleton className="h-80 w-full" />;
  if (me.data?.role !== "admin") return <Navigate to="/" replace />;
  if (summary.isPending || tiers.isPending || accounts.isPending) return <Skeleton className="h-[38rem] w-full" />;
  if (summary.isError || tiers.isError || accounts.isError || !summary.data || !tiers.data || !accounts.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Quota console unavailable</AlertTitle>
        <AlertDescription>{summary.error?.message ?? tiers.error?.message ?? accounts.error?.message}</AlertDescription>
      </Alert>
    );
  }

  const runway = summary.data.monthlyCapMicros
    ? (summary.data.monthlySpendMicros / summary.data.monthlyCapMicros) * 100
    : 0;
  const auditRows = operations.data?.data ?? [];
  const auditedAccounts = auditRows.reduce((total, operation) => total + operation.affectedCount, 0);

  return (
    <div className="flex flex-col gap-7">
      <PageHeader
        kicker="Metering console"
        title="Cost quotas"
        sub="Control recurring allowances, durable credits, pricing coverage, and auditable balance changes."
      />

      <section aria-labelledby="platform-runway-title" className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="flex flex-col gap-4 border-b bg-muted/25 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background text-primary">
              <Gauge className="size-4" aria-hidden="true" />
            </div>
            <div>
              <h2 id="platform-runway-title" className="font-semibold">Shared-key runway</h2>
              <p className="mt-0.5 text-sm text-muted-foreground">Platform-wide cost for the current UTC billing month.</p>
            </div>
          </div>
          <Link to="/account" className={buttonVariants({ variant: "outline", size: "sm" })}>
            <CircleUserRound data-icon="inline-start" />
            View my usage
          </Link>
        </div>
        <div className="p-5">
          <dl className="grid gap-5 sm:grid-cols-2 xl:grid-cols-5">
            <Metric label="Month spend" value={usd(t, summary.data.monthlySpendMicros)} detail="Shared platform keys" />
            <Metric label="Platform cap" value={usd(t, summary.data.monthlyCapMicros)} detail="UTC calendar month" />
            <Metric label="Runway" value={usd(t, summary.data.remainingMicros)} detail={`${Math.max(0, 100 - runway).toFixed(1)}% remains`} warning={runway >= 80} />
            <Metric label="Unpriced calls" value={String(summary.data.unpricedCallCount)} detail="Requires rate coverage" warning={summary.data.unpricedCallCount > 0} />
            <Metric label="Next reset" value={new Date(summary.data.nextResetAt).toLocaleDateString(undefined, { month: "short", day: "numeric" })} detail="00:00 UTC" />
          </dl>
          <Progress className="mt-6" value={Math.min(100, runway)}>
            <ProgressLabel>Shared-key monthly cap</ProgressLabel>
            <ProgressValue>{() => `${runway.toFixed(1)}%`}</ProgressValue>
          </Progress>
        </div>
      </section>

      <Tabs defaultValue="members">
        <div className="overflow-x-auto border-b">
          <TabsList className="h-11 gap-5" variant="line" aria-label="Quota console sections">
            <TabsTrigger className="px-1" value="members"><Users /> Members</TabsTrigger>
            <TabsTrigger className="px-1" value="tiers"><Layers3 /> Tiers</TabsTrigger>
            <TabsTrigger className="px-1" value="rates"><Gauge /> Rate cards</TabsTrigger>
            <TabsTrigger className="px-1" value="audit"><History /> Audit</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="members" className="space-y-5 pt-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex w-full max-w-xl flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input className="h-9 pl-9" aria-label="Search members" placeholder="Search member…" value={search} onChange={(event) => setSearch(event.target.value)} />
              </div>
              <Select value={balanceFilter} onValueChange={(value) => setBalanceFilter(value ?? "")}>
                <SelectTrigger size="compact" className={cn(CONTROL_TRIGGER, "sm:w-44")} aria-label="Balance filter"><SelectValue>{(value) => t(BALANCE_LABEL_KEYS[value as string] ?? BALANCE_LABEL_KEYS[ALL_BALANCES])}</SelectValue></SelectTrigger>
                <SelectContent>
                  {Object.entries(BALANCE_LABEL_KEYS).map(([value, labelKey]) => (
                    <SelectItem key={value} value={value}>{t(labelKey)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-xs text-muted-foreground">{filtered.length} shown · administrators are quota-exempt</p>
          </div>

          <QuotaOperationCard
            accounts={accounts.data.data}
            tiers={tiers.data.data}
            targetTypes={["USER", "ALL_MEMBERS"]}
            title="Member balance operation"
            description="Use this for one member or every member. Member plan and override settings stay in the member drawer below."
          />

          <Card className="overflow-hidden">
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Member</TableHead>
                    <TableHead>Tier</TableHead>
                    <TableHead>Period spend</TableHead>
                    <TableHead>Remaining</TableHead>
                    <TableHead>Credits</TableHead>
                    <TableHead>Shared / BYOK</TableHead>
                    <TableHead>Tokens</TableHead>
                    <TableHead>Reset</TableHead>
                    <TableHead><span className="sr-only">Manage member</span></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((account) => (
                    <TableRow key={account.userId}>
                      <TableCell><div className="font-medium">{account.username}</div>{account.disabled ? <span className="text-xs text-muted-foreground">Disabled</span> : null}</TableCell>
                      <TableCell><Badge variant="outline">{account.tierId}</Badge></TableCell>
                      <TableCell className="font-mono">{usd(t, account.spentMicros)}</TableCell>
                      <TableCell className="font-mono">{usd(t, account.remainingMicros)}</TableCell>
                      <TableCell className="font-mono">{usd(t, account.creditBalanceMicros)}</TableCell>
                      <TableCell className="font-mono">{usd(t, account.sharedCostMicros)} / {usd(t, account.byokCostMicros)}</TableCell>
                      <TableCell className="font-mono">{tokens(account.totalTokens)}</TableCell>
                      <TableCell className="font-mono">{new Date(account.periodEnd).toLocaleDateString()}</TableCell>
                      <TableCell><Button size="sm" variant="ghost" onClick={() => setSelected(account)}>Manage</Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {filtered.length === 0 ? (
                <div className="px-6 py-12 text-center">
                  <p className="font-medium">No member accounts match</p>
                  <p className="mt-1 text-sm text-muted-foreground">Adjust the search or balance filter to see more accounts.</p>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tiers"><TierPanel tiers={tiers.data.data} accounts={accounts.data.data} /></TabsContent>

        <TabsContent value="rates" className="space-y-5 pt-4">
          <RateCreator rates={rates.data?.data ?? []} />
          {rates.isError ? (
            <Alert variant="destructive"><AlertTitle>Rate cards unavailable</AlertTitle><AlertDescription>{rates.error.message}</AlertDescription></Alert>
          ) : null}
          {!rates.isError ? (
            <Card>
              <CardHeader>
                <CardTitle><h2 className="text-base">Effective rate cards</h2></CardTitle>
                <CardDescription>Models are grouped into one block and their immutable versions stay newest-first. Sort any column to rank model groups by the latest version.</CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <div className="flex flex-wrap gap-x-4 gap-y-2 border-y bg-muted/15 px-4 py-2.5 text-xs text-muted-foreground" aria-label="Rate card color legend">
                  {(Object.entries(RATE_COST_BAND_STYLES) as [RateCostBand, typeof RATE_COST_BAND_STYLES[RateCostBand]][]).map(([band, tone]) => (
                    <span key={band} className="inline-flex items-center gap-1.5">
                      <i aria-hidden="true" className={cn("size-2 rounded-full", tone.rail)} />
                      <span className="font-medium text-foreground">{t(RATE_COST_BAND_LABEL_KEYS[band])}</span>
                      <span>{t(RATE_COST_BAND_DETAIL_KEYS[band])}</span>
                    </span>
                  ))}
                </div>
                {(rates.data?.data ?? []).length > 0 ? (
                  <div className="max-h-[44rem] overflow-auto">
                    <RateVersionsTable rates={rates.data?.data ?? []} />
                  </div>
                ) : <div className="py-10 text-center text-sm text-muted-foreground">No rate cards found.</div>}
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>

        <TabsContent value="audit" className="space-y-5 pt-4">
          {operations.isError ? (
            <Alert variant="destructive"><AlertTitle>Audit log unavailable</AlertTitle><AlertDescription>{operations.error.message}</AlertDescription></Alert>
          ) : null}
          {!operations.isError ? (
            <>
              <dl className="grid gap-4 sm:grid-cols-3">
                <Metric label="Recorded operations" value={String(auditRows.length)} detail="Most recent results" />
                <Metric label="Accounts affected" value={String(auditedAccounts)} detail="Across listed operations" />
                <Metric label="Latest activity" value={auditRows[0] ? new Date(auditRows[0].createdAt).toLocaleDateString() : "—"} detail="Committed only" />
              </dl>
              <Card>
                <CardHeader>
                  <CardTitle><h2 className="text-base">Quota operation ledger</h2></CardTitle>
                  <CardDescription>Every committed bulk operation retains its target, audit reason, effect, actor, and timestamp.</CardDescription>
                </CardHeader>
                <CardContent className="overflow-x-auto p-0">
                  <Table>
                    <TableHeader><TableRow><TableHead>Action</TableHead><TableHead>Target</TableHead><TableHead>Amount</TableHead><TableHead>Affected</TableHead><TableHead>Reason</TableHead><TableHead>Actor</TableHead><TableHead>Timestamp</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {auditRows.map((operation) => (
                        <TableRow key={operation.id}>
                          <TableCell><Badge variant="outline">{quotaActionLabel(t, operation.actionType)}</Badge></TableCell>
                          <TableCell>{operationTargetLabel(t, operation, accounts.data.data, tiers.data.data)}</TableCell>
                          <TableCell className="font-mono">{optionalUsd(t, operation.amountMicros)}</TableCell>
                          <TableCell>{operation.affectedCount}</TableCell>
                          <TableCell className="max-w-xs">{operation.reason}</TableCell>
                          <TableCell className="font-mono text-xs">{operation.actorUserId}</TableCell>
                          <TableCell className="text-xs"><Clock3 className="mr-1 inline size-3" />{new Date(operation.createdAt).toLocaleString()}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {auditRows.length === 0 ? <div className="px-6 py-12 text-center text-sm text-muted-foreground">No committed quota operations yet.</div> : null}
                </CardContent>
              </Card>
            </>
          ) : null}
        </TabsContent>
      </Tabs>

      <AccountDrawer
        account={selected}
        tiers={tiers.data.data}
        open={selected != null}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </div>
  );
}
