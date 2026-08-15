import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Banknote,
  CircleUserRound,
  Clock3,
  Gauge,
  History,
  Layers3,
  Search,
  Users,
} from "lucide-react";
import { Link, Navigate } from "react-router-dom";

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
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type QuotaAccount = components["schemas"]["QuotaAccountOut"];
type QuotaPreview = components["schemas"]["QuotaOperationPreviewOut"];
type QuotaTier = components["schemas"]["QuotaTierOut"];
type LlmRate = components["schemas"]["LlmRateOut"];

type QuotaTargetType = "USER" | "TIER" | "ALL_MEMBERS";
type QuotaActionType = "RESET_CURRENT_PERIOD" | "GRANT_CREDIT" | "DEBIT_CREDIT";
type CycleUnit = "WEEK" | "MONTH";
type RatePeriodChoice = "all" | "peak" | "off_peak";

const MICROS_PER_USD = 1_000_000;
const CUSTOM_MODEL = "__custom__";
const ALL_BALANCES = "ALL";
const PROVIDERS = ["anthropic", "openai", "gemini", "deepseek"] as const;
const CYCLE_COUNTS = Array.from({ length: 52 }, (_, index) => index + 1);

const TARGET_LABELS: Record<QuotaTargetType, string> = {
  USER: "One member",
  TIER: "One tier",
  ALL_MEMBERS: "All members",
};

const ACTION_LABELS: Record<QuotaActionType, string> = {
  GRANT_CREDIT: "Grant credit",
  DEBIT_CREDIT: "Debit credit",
  RESET_CURRENT_PERIOD: "Reset current period",
};

function usd(micros: number | null | undefined): string {
  if (micros == null) return "Unlimited";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(micros / MICROS_PER_USD);
}

function optionalUsd(micros: number | null | undefined): string {
  return micros == null ? "—" : usd(micros);
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

function readableCycle(unit: CycleUnit, count: number): string {
  const label = unit === "WEEK" ? "week" : "month";
  return count === 1 ? `Every ${label}` : `Every ${count} ${label}s`;
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
                    {account.status}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Period spend</dt>
                <dd className="mt-1 font-mono">{usd(account.spentMicros)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Credits</dt>
                <dd className="mt-1 font-mono">{usd(account.creditBalanceMicros)}</dd>
              </div>
            </dl>

            <div className="space-y-1.5">
              <Label htmlFor="drawer-tier">Assign tier</Label>
              <Select value={tierId} onValueChange={(value) => setTierId(value ?? "")}>
                <SelectTrigger id="drawer-tier" size="compact" className="w-full" aria-label="Assign member tier">
                  <SelectValue placeholder={`Keep ${account.tierId}`} />
                </SelectTrigger>
                <SelectContent>
                  {tiers.map((tier) => (
                    <SelectItem key={tier.id} value={tier.id}>
                      {tier.name} · {tier.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

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

            <div className="space-y-1.5">
              <Label htmlFor="drawer-reason">Audit reason</Label>
              <Input
                id="drawer-reason"
                className="h-9"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why is this member change needed?"
              />
            </div>
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
                        <span className="font-medium">{entry.kind.replaceAll("_", " ")}</span>
                        <span className="font-mono">{usd(entry.amountMicros)}</span>
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
    <Card className="border-amber-500/35 bg-amber-500/[0.035]">
      <CardHeader>
        <CardTitle>
          <h2 className="flex items-center gap-2 text-base">
            <Banknote className="size-4" aria-hidden="true" />
            {title}
          </h2>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className={`grid gap-3 sm:grid-cols-2 ${
            targetTypes.length > 1
              ? "xl:grid-cols-[10rem_minmax(14rem,1fr)_13rem_10rem]"
              : "xl:grid-cols-[minmax(14rem,1fr)_13rem_10rem]"
          }`}
        >
          {targetTypes.length > 1 ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${title}-scope`}>Scope</Label>
              <Select value={targetType} onValueChange={(value) => changeTargetType(value as QuotaTargetType)}>
                <SelectTrigger id={`${title}-scope`} size="compact" className="w-full" aria-label="Target scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {targetTypes.map((type) => (
                    <SelectItem key={type} value={type}>{TARGET_LABELS[type]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {targetType === "USER" ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${title}-member`}>Member</Label>
              <Select
                value={targetValue}
                onValueChange={(value) => {
                  setTargetValue(value ?? "");
                  clearPreview();
                }}
              >
                <SelectTrigger id={`${title}-member`} size="compact" className="w-full" aria-label="Target member">
                  <SelectValue placeholder="Choose a member" />
                </SelectTrigger>
                <SelectContent>
                  {accounts.map((account) => (
                    <SelectItem key={account.userId} value={account.userId}>
                      {account.username} · {account.tierId}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {targetType === "TIER" ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${title}-tier`}>Tier</Label>
              <Select
                value={targetValue}
                onValueChange={(value) => {
                  setTargetValue(value ?? "");
                  clearPreview();
                }}
              >
                <SelectTrigger id={`${title}-tier`} size="compact" className="w-full" aria-label="Target tier">
                  <SelectValue placeholder="Choose a tier" />
                </SelectTrigger>
                <SelectContent>
                  {tiers.map((tier) => (
                    <SelectItem key={tier.id} value={tier.id}>
                      {tier.name} · {tier.memberCount} members
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {targetType === "ALL_MEMBERS" ? (
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Target</p>
              <div className="flex h-9 items-center rounded-lg border bg-background/70 px-3 text-sm">
                All {accounts.length} member accounts
              </div>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor={`${title}-action`}>Action</Label>
            <Select
              value={actionType}
              onValueChange={(value) => {
                setActionType(value as QuotaActionType);
                clearPreview();
              }}
            >
              <SelectTrigger id={`${title}-action`} size="compact" className="w-full" aria-label="Quota action">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ACTION_LABELS) as QuotaActionType[]).map((action) => (
                  <SelectItem key={action} value={action}>{ACTION_LABELS[action]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {requiresAmount ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${title}-amount`}>Amount (USD)</Label>
              <Input
                id={`${title}-amount`}
                className="h-9"
                aria-invalid={amount !== "" && amountMicros == null}
                inputMode="decimal"
                placeholder="e.g. 10.00"
                value={amount}
                onChange={(event) => {
                  setAmount(event.target.value);
                  clearPreview();
                }}
              />
            </div>
          ) : (
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Effect</p>
              <div className="flex h-9 items-center rounded-lg border bg-background/70 px-3 text-sm">
                Reset current period
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3 border-t pt-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="w-full space-y-1.5 lg:max-w-2xl">
            <Label htmlFor={`${title}-reason`}>Audit reason</Label>
            <Input
              id={`${title}-reason`}
              className="h-9"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Required only when confirming this operation"
            />
          </div>
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
          <div className="flex flex-col gap-3 rounded-lg border border-amber-500/40 bg-background p-4 sm:flex-row sm:items-center">
            <AlertTriangle className="size-5 shrink-0 text-amber-600" aria-hidden="true" />
            <div className="flex-1">
              <div className="font-medium">
                {preview.affectedCount} account{preview.affectedCount === 1 ? "" : "s"} frozen for review
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                Total effect {usd(preview.totalEffectMicros)} · preview expires {new Date(preview.expiresAt).toLocaleTimeString()}
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

type TierDraft = {
  name?: string;
  cycleUnit?: CycleUnit;
  cycleCount?: string;
  allowance?: string;
};

function TierPanel({ tiers, accounts }: { tiers: QuotaTier[]; accounts: QuotaAccount[] }) {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [newAllowance, setNewAllowance] = useState("");
  const [newCycleUnit, setNewCycleUnit] = useState<CycleUnit>("MONTH");
  const [newCycleCount, setNewCycleCount] = useState("1");
  const [reason, setReason] = useState("");
  const [selectedTierId, setSelectedTierId] = useState("");
  const [drafts, setDrafts] = useState<Record<string, TierDraft>>({});

  const selectedTier = tiers.find((tier) => tier.id === selectedTierId) ?? tiers[0] ?? null;
  const selectedDraft = selectedTier ? drafts[selectedTier.id] ?? {} : {};
  const selectedName = selectedTier ? selectedDraft.name ?? selectedTier.name : "";
  const selectedCycleUnit = selectedTier ? selectedDraft.cycleUnit ?? selectedTier.cycleUnit : "MONTH";
  const selectedCycleCount = selectedTier ? selectedDraft.cycleCount ?? String(selectedTier.cycleCount) : "1";
  const selectedAllowance = selectedTier
    ? selectedDraft.allowance ?? usdInputValue(selectedTier.allowanceMicros)
    : "";
  const newAllowanceMicros = optionalMicros(newAllowance);
  const selectedAllowanceMicros = optionalMicros(selectedAllowance);
  const derivedId = tierIdFromName(newName);

  function updateDraft(changes: TierDraft) {
    if (!selectedTier) return;
    setDrafts((current) => ({
      ...current,
      [selectedTier.id]: { ...current[selectedTier.id], ...changes },
    }));
  }

  function buildTierPatch() {
    if (!selectedTier) return null;
    const nextName = selectedName.trim();
    const nextCycleCount = Number(selectedCycleCount);
    const body: {
      name?: string;
      cycleUnit?: CycleUnit;
      cycleCount?: number;
      allowanceMicros?: number | null;
      reason: string;
    } = { reason };
    if (nextName !== selectedTier.name) body.name = nextName;
    if (selectedCycleUnit !== selectedTier.cycleUnit) body.cycleUnit = selectedCycleUnit;
    if (nextCycleCount !== selectedTier.cycleCount) body.cycleCount = nextCycleCount;
    if (selectedAllowanceMicros !== selectedTier.allowanceMicros) {
      body.allowanceMicros = selectedAllowanceMicros;
    }
    return body;
  }

  const patchBody = buildTierPatch();
  const hasTierChanges = patchBody != null && Object.keys(patchBody).length > 1;
  const canCreate = Boolean(newName.trim()) && newAllowanceMicros !== undefined && Boolean(reason.trim());
  const canSave = Boolean(
    selectedTier
    && selectedName.trim()
    && selectedAllowanceMicros !== undefined
    && hasTierChanges
    && reason.trim(),
  );

  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/quota-tiers", {
      body: {
        id: derivedId,
        name: newName.trim(),
        cycleUnit: newCycleUnit,
        cycleCount: Number(newCycleCount),
        allowanceMicros: newAllowanceMicros ?? null,
        reason,
      },
    })),
    onSuccess: () => {
      setNewName("");
      setNewAllowance("");
      setNewCycleUnit("MONTH");
      setNewCycleCount("1");
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-tiers"] });
    },
  });
  const save = useMutation({
    mutationFn: () => {
      if (!selectedTier || !patchBody || !hasTierChanges) throw new Error("No tier changes to save");
      return unwrap(api.PATCH("/api/admin/quota-tiers/{tier_id}", {
        params: { path: { tier_id: selectedTier.id } },
        body: patchBody,
      }));
    },
    onSuccess: () => {
      if (selectedTier) {
        setDrafts((current) => {
          const next = { ...current };
          delete next[selectedTier.id];
          return next;
        });
      }
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-tiers"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
    },
  });
  const archive = useMutation({
    mutationFn: () => {
      if (!selectedTier) throw new Error("No tier selected");
      return unwrap(api.PATCH("/api/admin/quota-tiers/{tier_id}", {
        params: { path: { tier_id: selectedTier.id } },
        body: { archived: true, reason },
      }));
    },
    onSuccess: () => {
      setReason("");
      setSelectedTierId("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-tiers"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
    },
  });

  return (
    <div className="space-y-5 pt-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle><h2 className="text-base">Tier configuration</h2></CardTitle>
          <CardDescription>
            Name a new plan once; its stable identifier is derived automatically. Select an existing tier to revise it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="max-w-2xl space-y-1.5">
            <Label htmlFor="tier-change-reason">Audit reason for the next tier action</Label>
            <Input
              id="tier-change-reason"
              className="h-9"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why is this tier being created, changed, or archived?"
            />
            <p className="text-xs text-muted-foreground">Shared by create, save, and archive actions below.</p>
          </div>

          <div className="grid gap-4 border-t pt-4 xl:grid-cols-2 xl:items-start">
          <section className="space-y-4 rounded-lg border bg-muted/10 p-4" aria-labelledby="create-tier-title">
            <div>
              <h3 id="create-tier-title" className="font-medium">Create allowance tier</h3>
              <p className="mt-1 text-sm text-muted-foreground">Add a recurring allowance plan.</p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="min-w-0 flex-1 space-y-1.5">
                <Label htmlFor="new-tier-name">Tier name</Label>
                <Input
                  id="new-tier-name"
                  className="h-9"
                  placeholder="e.g. Team"
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                />
              </div>
              <div className="w-full space-y-1.5 sm:w-36">
                <Label htmlFor="new-tier-allowance">Allowance (USD)</Label>
                <Input
                  id="new-tier-allowance"
                  className="h-9"
                  aria-invalid={newAllowance !== "" && newAllowanceMicros === undefined}
                  inputMode="decimal"
                  placeholder="Unlimited"
                  value={newAllowance}
                  onChange={(event) => setNewAllowance(event.target.value)}
                />
              </div>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="w-full space-y-1.5 sm:w-36">
                <Label htmlFor="new-tier-unit">Cadence</Label>
                <Select value={newCycleUnit} onValueChange={(value) => setNewCycleUnit(value as CycleUnit)}>
                  <SelectTrigger id="new-tier-unit" size="compact" className="w-full" aria-label="New tier cadence unit">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MONTH">Months</SelectItem>
                    <SelectItem value="WEEK">Weeks</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="w-full space-y-1.5 sm:w-24">
                <Label htmlFor="new-tier-count">Every</Label>
                <Select value={newCycleCount} onValueChange={(value) => setNewCycleCount(value ?? "1")}>
                  <SelectTrigger id="new-tier-count" size="compact" className="w-full" aria-label="New tier cadence count">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CYCLE_COUNTS.map((count) => <SelectItem key={count} value={String(count)}>{count}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center justify-between gap-3 border-t pt-3">
              <p className="truncate text-xs text-muted-foreground">
                ID <span className="font-mono text-foreground">{derivedId}</span>
              </p>
              <Button size="sm" disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>
                {create.isPending ? "Creating…" : "Create tier"}
              </Button>
            </div>
          </section>

          <section className="space-y-4 rounded-lg border bg-muted/10 p-4" aria-labelledby="edit-tier-title">
            <div>
              <h3 id="edit-tier-title" className="font-medium">Edit existing tier</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Choose a tier, then adjust only the values that need to change.
              </p>
            </div>
            {selectedTier ? (
              <div className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Label htmlFor="selected-tier">Tier</Label>
                    <Select
                      value={selectedTier.id}
                      onValueChange={(value) => setSelectedTierId(value ?? "")}
                    >
                      <SelectTrigger id="selected-tier" size="compact" className="w-full" aria-label="Tier to edit">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {tiers.map((tier) => (
                          <SelectItem key={tier.id} value={tier.id}>{tier.name} · {tier.id}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="w-full space-y-1.5 sm:w-36">
                    <Label htmlFor="selected-tier-allowance">Allowance (USD)</Label>
                    <Input
                      id="selected-tier-allowance"
                      className="h-9"
                      aria-invalid={selectedAllowance !== "" && selectedAllowanceMicros === undefined}
                      inputMode="decimal"
                      placeholder="Unlimited"
                      value={selectedAllowance}
                      onChange={(event) => updateDraft({ allowance: event.target.value })}
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Label htmlFor="selected-tier-name">Tier name</Label>
                    <Input
                      id="selected-tier-name"
                      className="h-9"
                      value={selectedName}
                      onChange={(event) => updateDraft({ name: event.target.value })}
                    />
                  </div>
                  <div className="w-full space-y-1.5 sm:w-36">
                    <Label htmlFor="selected-tier-unit">Cadence</Label>
                    <Select
                      value={selectedCycleUnit}
                      onValueChange={(value) => updateDraft({ cycleUnit: value as CycleUnit })}
                    >
                      <SelectTrigger id="selected-tier-unit" size="compact" className="w-full" aria-label="Tier cadence unit">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="MONTH">Months</SelectItem>
                        <SelectItem value="WEEK">Weeks</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="w-full space-y-1.5 sm:w-24">
                    <Label htmlFor="selected-tier-count">Every</Label>
                    <Select
                      value={selectedCycleCount}
                      onValueChange={(value) => updateDraft({ cycleCount: value ?? "1" })}
                    >
                      <SelectTrigger id="selected-tier-count" size="compact" className="w-full" aria-label="Tier cadence count">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {CYCLE_COUNTS.map((count) => <SelectItem key={count} value={String(count)}>{count}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <dl className="grid gap-3 border-t pt-3 text-sm sm:grid-cols-3">
                  <div><dt className="text-muted-foreground">Members</dt><dd className="mt-1 font-mono">{selectedTier.memberCount}</dd></div>
                  <div><dt className="text-muted-foreground">Open-period spend</dt><dd className="mt-1 font-mono">{usd(selectedTier.spendMicros)}</dd></div>
                  <div><dt className="text-muted-foreground">Current cycle</dt><dd className="mt-1">{readableCycle(selectedTier.cycleUnit, selectedTier.cycleCount)}</dd></div>
                </dl>
                <div className="flex justify-end gap-2 border-t pt-3">
                  {!selectedTier.isDefault ? (
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={!reason.trim() || archive.isPending}
                      onClick={() => archive.mutate()}
                    >
                      {archive.isPending ? "Archiving…" : "Archive tier"}
                    </Button>
                  ) : null}
                  <Button size="sm" disabled={!canSave || save.isPending} onClick={() => save.mutate()}>
                    {save.isPending ? "Saving…" : "Save tier"}
                  </Button>
                </div>
              </div>
            ) : (
              <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
                Create a tier to begin configuring it.
              </p>
            )}
          </section>
          </div>
          {create.isError || save.isError || archive.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Tier update failed</AlertTitle>
              <AlertDescription>{create.error?.message ?? save.error?.message ?? archive.error?.message}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>

      <QuotaOperationCard
        accounts={accounts}
        tiers={tiers}
        targetTypes={["TIER"]}
        title="Tier balance operation"
        description="Apply one audited credit or period action to the members currently assigned to a selected tier."
      />

      <section aria-labelledby="tier-overview-title" className="space-y-3">
        <div>
          <h2 id="tier-overview-title" className="font-medium">Tier overview</h2>
          <p className="mt-1 text-sm text-muted-foreground">Choose a tier above to edit it; these cards are read-only summaries.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {tiers.map((tier) => (
            <Card key={tier.id} className={selectedTier?.id === tier.id ? "border-primary/50" : undefined}>
              <CardHeader>
                <div className="flex items-center justify-between gap-3">
                  <CardTitle><h3 className="text-base">{tier.name}</h3></CardTitle>
                  <Badge variant={tier.isDefault ? "default" : "outline"}>{tier.id}</Badge>
                </div>
                <CardDescription>{readableCycle(tier.cycleUnit, tier.cycleCount)} · {tier.memberCount} members</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="font-mono text-3xl font-semibold">{usd(tier.allowanceMicros)}</div>
                <div className="mt-3 flex justify-between text-xs text-muted-foreground">
                  <span>Open-period spend</span>
                  <span className="font-mono">{usd(tier.spendMicros)}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}

function RateCreator({ rates }: { rates: LlmRate[] }) {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]>("anthropic");
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

  function changeProvider(value: (typeof PROVIDERS)[number]) {
    setProvider(value);
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
          <div className="w-full space-y-1.5 sm:w-40">
            <Label htmlFor="rate-provider">Provider</Label>
            <Select value={provider} onValueChange={(value) => changeProvider(value as (typeof PROVIDERS)[number])}>
              <SelectTrigger id="rate-provider" size="compact" className="w-full" aria-label="Rate provider"><SelectValue /></SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="w-full space-y-1.5 sm:w-64">
            <Label htmlFor="rate-model">Model</Label>
            <Select value={modelChoice} onValueChange={(value) => setModelChoice(value ?? CUSTOM_MODEL)}>
              <SelectTrigger id="rate-model" size="compact" className="w-full" aria-label="Rate model"><SelectValue /></SelectTrigger>
              <SelectContent>
                {models.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
                <SelectItem value={CUSTOM_MODEL}>Another model identifier</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {modelChoice === CUSTOM_MODEL ? (
            <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-56">
              <Label htmlFor="custom-rate-model">Model identifier</Label>
              <Input id="custom-rate-model" className="h-9" placeholder="model-id" value={customModel} onChange={(event) => setCustomModel(event.target.value)} />
            </div>
          ) : null}
          <div className="w-full space-y-1.5 sm:w-40">
            <Label htmlFor="rate-input">Input (USD / 1M)</Label>
            <Input id="rate-input" className="h-9" aria-invalid={input !== "" && inputMicros == null} inputMode="decimal" placeholder="e.g. 3.00" value={input} onChange={(event) => setInput(event.target.value)} />
          </div>
          <div className="w-full space-y-1.5 sm:w-40">
            <Label htmlFor="rate-output">Output (USD / 1M)</Label>
            <Input id="rate-output" className="h-9" aria-invalid={output !== "" && outputMicros == null} inputMode="decimal" placeholder="e.g. 15.00" value={output} onChange={(event) => setOutput(event.target.value)} />
          </div>
          {provider === "deepseek" ? (
            <div className="w-full space-y-1.5 sm:w-40">
              <Label htmlFor="rate-period">Billing hours</Label>
              <Select value={ratePeriod} onValueChange={(value) => setRatePeriod(value as RatePeriodChoice)}>
                <SelectTrigger id="rate-period" size="compact" className="w-full" aria-label="Rate billing hours"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Every hour</SelectItem>
                  <SelectItem value="peak">Peak hours</SelectItem>
                  <SelectItem value="off_peak">Off-peak hours</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}
          <div className="w-full space-y-1.5 sm:w-56">
            <Label htmlFor="rate-effective">Effective from</Label>
            <Input id="rate-effective" className="h-9" type="datetime-local" value={effective} onChange={(event) => setEffective(event.target.value)} />
          </div>
          <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-72">
            <Label htmlFor="rate-source">Official pricing source</Label>
            <Input id="rate-source" className="h-9" type="url" placeholder="https://…" value={source} onChange={(event) => setSource(event.target.value)} />
          </div>
        </div>

        <div className="rounded-lg border bg-muted/10 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <Label htmlFor="optional-rate-fields" className="text-sm font-medium">Optional cache and tool rates</Label>
              <p className="mt-1 text-xs text-muted-foreground">Leave these blank when the provider does not charge them.</p>
            </div>
            <Switch id="optional-rate-fields" checked={showOptionalRates} onCheckedChange={setShowOptionalRates} />
          </div>
          {showOptionalRates ? (
            <div className="mt-3 flex flex-wrap gap-3">
              <div className="w-full space-y-1.5 sm:w-52"><Label htmlFor="rate-cache-read">Cache read (USD / 1M)</Label><Input id="rate-cache-read" className="h-9" inputMode="decimal" value={cacheRead} onChange={(event) => setCacheRead(event.target.value)} /></div>
              <div className="w-full space-y-1.5 sm:w-52"><Label htmlFor="rate-cache-write">Cache write (USD / 1M)</Label><Input id="rate-cache-write" className="h-9" inputMode="decimal" value={cacheWrite} onChange={(event) => setCacheWrite(event.target.value)} /></div>
              <div className="w-full space-y-1.5 sm:w-48"><Label htmlFor="rate-tool-fee">Tool fee (USD / unit)</Label><Input id="rate-tool-fee" className="h-9" inputMode="decimal" value={toolFee} onChange={(event) => setToolFee(event.target.value)} /></div>
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-3 border-t pt-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="w-full space-y-1.5 lg:max-w-2xl">
            <Label htmlFor="rate-reason">Audit reason</Label>
            <Input id="rate-reason" className="h-9" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why is this pricing version being added?" />
          </div>
          <Button size="sm" disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Creating…" : "Create immutable version"}
          </Button>
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

function operationTarget(
  operation: components["schemas"]["QuotaOperationOut"],
  accounts: QuotaAccount[],
  tiers: QuotaTier[],
): string {
  if (operation.targetType === "ALL_MEMBERS") return "All members";
  if (operation.targetType === "USER") {
    return accounts.find((account) => account.userId === operation.targetValue)?.username ?? operation.targetValue ?? "Member";
  }
  const tier = tiers.find((item) => item.id === operation.targetValue);
  return tier ? `${tier.name} · ${tier.id}` : operation.targetValue ?? "Tier";
}

export function AdminQuotasPage() {
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
            <Metric label="Month spend" value={usd(summary.data.monthlySpendMicros)} detail="Shared platform keys" />
            <Metric label="Platform cap" value={usd(summary.data.monthlyCapMicros)} detail="UTC calendar month" />
            <Metric label="Runway" value={usd(summary.data.remainingMicros)} detail={`${Math.max(0, 100 - runway).toFixed(1)}% remains`} warning={runway >= 80} />
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
                <SelectTrigger size="compact" className="w-full sm:w-44" aria-label="Balance filter"><SelectValue placeholder="All balances" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_BALANCES}>All balances</SelectItem>
                  <SelectItem value="POSITIVE">Positive</SelectItem>
                  <SelectItem value="ZERO">Depleted</SelectItem>
                  <SelectItem value="OVERAGE">Overage</SelectItem>
                  <SelectItem value="UNLIMITED">Unlimited</SelectItem>
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
                      <TableCell className="font-mono">{usd(account.spentMicros)}</TableCell>
                      <TableCell className="font-mono">{usd(account.remainingMicros)}</TableCell>
                      <TableCell className="font-mono">{usd(account.creditBalanceMicros)}</TableCell>
                      <TableCell className="font-mono">{usd(account.sharedCostMicros)} / {usd(account.byokCostMicros)}</TableCell>
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
                <CardTitle><h2 className="text-base">Effective rate versions</h2></CardTitle>
                <CardDescription>Exact provider, model, context band, rate period, and effective window determine coverage.</CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto p-0">
                <Table>
                  <TableHeader><TableRow><TableHead>Provider / model</TableHead><TableHead>Context band</TableHead><TableHead>Input</TableHead><TableHead>Cache read / write</TableHead><TableHead>Output</TableHead><TableHead>Tool fee</TableHead><TableHead>Hours</TableHead><TableHead>Effective</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {(rates.data?.data ?? []).map((rate) => (
                      <TableRow key={rate.id}>
                        <TableCell><div className="font-medium">{rate.provider}</div><div className="font-mono text-xs text-muted-foreground">{rate.model}</div></TableCell>
                        <TableCell className="font-mono">{tokens(rate.contextMinTokens)}–{rate.contextMaxTokens == null ? "∞" : tokens(rate.contextMaxTokens)}</TableCell>
                        <TableCell className="font-mono">{usd(rate.inputMicrosPerMillion)}</TableCell>
                        <TableCell className="font-mono">{optionalUsd(rate.cacheReadMicrosPerMillion)} / {optionalUsd(rate.cacheWriteMicrosPerMillion)}</TableCell>
                        <TableCell className="font-mono">{usd(rate.outputMicrosPerMillion)}</TableCell>
                        <TableCell className="font-mono">{optionalUsd(rate.toolMicrosPerUnit)}</TableCell>
                        <TableCell>{rate.ratePeriod ? rate.ratePeriod.replace("_", "-") : "Every hour"}</TableCell>
                        <TableCell className="font-mono"><div>{new Date(rate.effectiveFrom).toLocaleDateString()}</div><div className="text-xs text-muted-foreground">{rate.effectiveTo ? `to ${new Date(rate.effectiveTo).toLocaleDateString()}` : "active"}</div></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {rates.data?.data.length === 0 ? <div className="px-6 py-12 text-center text-sm text-muted-foreground">No rate cards found.</div> : null}
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
                          <TableCell><Badge variant="outline">{operation.actionType.replaceAll("_", " ")}</Badge></TableCell>
                          <TableCell>{operationTarget(operation, accounts.data.data, tiers.data.data)}</TableCell>
                          <TableCell className="font-mono">{optionalUsd(operation.amountMicros)}</TableCell>
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
