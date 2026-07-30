import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Banknote,
  Clock3,
  Gauge,
  History,
  Layers3,
  Search,
  Users,
} from "lucide-react";
import { Navigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useMe } from "@/features/auth/AuthGate";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type QuotaAccount = components["schemas"]["QuotaAccountOut"];
type QuotaPreview = components["schemas"]["QuotaOperationPreviewOut"];
type QuotaTier = components["schemas"]["QuotaTierOut"];

function usd(micros: number | null | undefined): string {
  if (micros == null) return "Unlimited";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(micros / 1_000_000);
}

function tokens(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

function Metric({ label, value, detail, warning = false }: { label: string; value: string; detail: string; warning?: boolean }) {
  return (
    <div className={`border-l-2 px-4 py-2 ${warning ? "border-amber-500" : "border-primary/50"}`}>
      <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-mono text-2xl font-semibold tabular-nums">{value}</dd>
      <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
    </div>
  );
}

function AccountDrawer({ account, open, onOpenChange }: { account: QuotaAccount | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [tierId, setTierId] = useState("");
  const [override, setOverride] = useState("");
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
      const body: { tierId?: string; allowanceOverrideMicros?: number | null; reason: string } = { reason };
      if (tierId) body.tierId = tierId;
      if (override !== "") body.allowanceOverrideMicros = Math.round(Number(override) * 1_000_000);
      return unwrap(api.PATCH("/api/admin/quota-accounts/{user_id}", {
        params: { path: { user_id: account.userId } }, body,
      }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
      setTierId(""); setOverride(""); setReason("");
    },
  });
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader className="border-b p-6">
          <SheetTitle>{account?.username ?? "Member quota"}</SheetTitle>
          <SheetDescription>Change tier or apply a persistent allowance override. Every change requires an audit reason.</SheetDescription>
        </SheetHeader>
        {account ? (
          <div className="space-y-6 p-6">
            <dl className="grid grid-cols-2 gap-4 rounded-lg border p-4 text-sm">
              <div><dt className="text-muted-foreground">Tier</dt><dd className="mt-1 font-mono">{account.tierId}</dd></div>
              <div><dt className="text-muted-foreground">Status</dt><dd className="mt-1"><Badge variant={account.status === "OVERAGE" ? "destructive" : "outline"}>{account.status}</Badge></dd></div>
              <div><dt className="text-muted-foreground">Period spend</dt><dd className="mt-1 font-mono">{usd(account.spentMicros)}</dd></div>
              <div><dt className="text-muted-foreground">Credits</dt><dd className="mt-1 font-mono">{usd(account.creditBalanceMicros)}</dd></div>
            </dl>
            <div className="space-y-2">
              <Label htmlFor="drawer-tier">Assign tier</Label>
              <Input id="drawer-tier" placeholder="FREE or SUBSCRIBER" value={tierId} onChange={(event) => setTierId(event.target.value.toUpperCase())} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="drawer-override">Allowance override in USD</Label>
              <Input id="drawer-override" inputMode="decimal" placeholder="Leave blank to keep current" value={override} onChange={(event) => setOverride(event.target.value)} />
              <p className="text-xs text-muted-foreground">Enter 0 for no recurring allowance. Clear an override from the API by sending null.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="drawer-reason">Audit reason</Label>
              <Textarea id="drawer-reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why is this change needed?" />
            </div>
            {patch.isError ? <Alert variant="destructive"><AlertTitle>Update failed</AlertTitle><AlertDescription>{patch.error.message}</AlertDescription></Alert> : null}
            <Button disabled={!reason.trim() || (!tierId && override === "") || patch.isPending} onClick={() => patch.mutate()}>{patch.isPending ? "Saving…" : "Save quota change"}</Button>
            <section aria-labelledby="member-ledger" className="space-y-3 border-t pt-5">
              <h3 id="member-ledger" className="font-semibold">Recent ledger</h3>
              {ledger.isPending ? <Skeleton className="h-24 w-full" /> : ledger.data?.data.length ? (
                <ul className="space-y-2">{ledger.data.data.map((entry) => <li key={entry.id} className="rounded-lg border p-3 text-xs"><div className="flex justify-between gap-3"><span className="font-medium">{entry.kind.replaceAll("_", " ")}</span><span className="font-mono">{usd(entry.amountMicros)}</span></div><div className="mt-1 text-muted-foreground">{entry.reason ?? "Automated usage accounting"} · {new Date(entry.createdAt).toLocaleString()}</div></li>)}</ul>
              ) : <p className="text-sm text-muted-foreground">No quota ledger entries yet.</p>}
            </section>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function BulkCommandBar({ accounts }: { accounts: QuotaAccount[] }) {
  const queryClient = useQueryClient();
  const [targetType, setTargetType] = useState<"USER" | "TIER" | "ALL_MEMBERS">("USER");
  const [targetValue, setTargetValue] = useState("");
  const [actionType, setActionType] = useState<"RESET_CURRENT_PERIOD" | "GRANT_CREDIT" | "DEBIT_CREDIT">("GRANT_CREDIT");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<QuotaPreview | null>(null);
  const previewMutation = useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/quota-operation-previews", { body: {
      targetType, targetValue: targetType === "ALL_MEMBERS" ? null : targetValue,
      actionType, amountMicros: actionType === "RESET_CURRENT_PERIOD" ? null : Math.round(Number(amount) * 1_000_000),
    } })),
    onSuccess: setPreview,
  });
  const commit = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("Preview required");
      return unwrap(api.POST("/api/admin/quota-operations", { body: {
        previewId: preview.id, reason, idempotencyKey: crypto.randomUUID(),
      } }));
    },
    onSuccess: () => {
      setPreview(null); setReason(""); setAmount("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "quota-operations"] });
    },
  });
  const validAmount = actionType === "RESET_CURRENT_PERIOD" || Number(amount) > 0;
  return (
    <Card className="border-amber-500/30 bg-amber-500/[0.03]">
      <CardHeader><CardTitle><h3 className="flex items-center gap-2"><Banknote className="size-4" /> Bulk quota command</h3></CardTitle><CardDescription>Freeze the target set, inspect the monetary effect, then commit with a reason.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-[0.8fr_1fr_1fr_0.8fr_1.5fr_auto]">
          <label className="space-y-1 text-xs font-medium">Scope<select aria-label="Target scope" className="mt-1 h-9 w-full rounded-lg border bg-background px-2 text-sm" value={targetType} onChange={(event) => { setTargetType(event.target.value as typeof targetType); setPreview(null); }}><option value="USER">User</option><option value="TIER">Tier</option><option value="ALL_MEMBERS">All members</option></select></label>
          <label className="space-y-1 text-xs font-medium">Target{targetType === "USER" ? <select aria-label="Target user" className="mt-1 h-9 w-full rounded-lg border bg-background px-2 text-sm" value={targetValue} onChange={(event) => setTargetValue(event.target.value)}><option value="">Select member</option>{accounts.map((account) => <option key={account.userId} value={account.userId}>{account.username}</option>)}</select> : <Input aria-label="Target value" className="mt-1" disabled={targetType === "ALL_MEMBERS"} placeholder={targetType === "TIER" ? "FREE" : "All members"} value={targetValue} onChange={(event) => setTargetValue(event.target.value.toUpperCase())} />}</label>
          <label className="space-y-1 text-xs font-medium">Action<select aria-label="Quota action" className="mt-1 h-9 w-full rounded-lg border bg-background px-2 text-sm" value={actionType} onChange={(event) => { setActionType(event.target.value as typeof actionType); setPreview(null); }}><option value="GRANT_CREDIT">Grant credit</option><option value="DEBIT_CREDIT">Debit credit</option><option value="RESET_CURRENT_PERIOD">Reset period</option></select></label>
          <label className="space-y-1 text-xs font-medium">USD amount<Input className="mt-1" inputMode="decimal" disabled={actionType === "RESET_CURRENT_PERIOD"} value={amount} onChange={(event) => { setAmount(event.target.value); setPreview(null); }} placeholder="10.00" /></label>
          <label className="space-y-1 text-xs font-medium">Reason<Input className="mt-1" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Required for commit" /></label>
          <Button className="self-end" variant="outline" disabled={!validAmount || (targetType !== "ALL_MEMBERS" && !targetValue) || previewMutation.isPending} onClick={() => previewMutation.mutate()}>Preview</Button>
        </div>
        {preview ? <div className="flex flex-col gap-3 rounded-lg border border-amber-500/40 bg-background p-4 sm:flex-row sm:items-center"><AlertTriangle className="size-5 text-amber-600" aria-hidden="true" /><div className="flex-1"><div className="font-medium">{preview.affectedCount} accounts frozen</div><div className="text-xs text-muted-foreground">Total effect {usd(preview.totalEffectMicros)} · expires {new Date(preview.expiresAt).toLocaleTimeString()}</div></div><Button variant={actionType === "DEBIT_CREDIT" || actionType === "RESET_CURRENT_PERIOD" ? "destructive" : "default"} disabled={!reason.trim() || commit.isPending} onClick={() => commit.mutate()}>{commit.isPending ? "Applying…" : "Confirm operation"}</Button></div> : null}
        {previewMutation.isError || commit.isError ? <Alert variant="destructive"><AlertTitle>Quota operation failed</AlertTitle><AlertDescription>{previewMutation.error?.message ?? commit.error?.message}</AlertDescription></Alert> : null}
      </CardContent>
    </Card>
  );
}

function TierPanel({ tiers }: { tiers: QuotaTier[] }) {
  const queryClient = useQueryClient();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [allowance, setAllowance] = useState("");
  const [reason, setReason] = useState("");
  const [edit, setEdit] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/quota-tiers", { body: {
      id, name, cycleUnit: "MONTH", cycleCount: 1,
      allowanceMicros: allowance === "" ? null : Math.round(Number(allowance) * 1_000_000), reason,
    } })),
    onSuccess: () => { setId(""); setName(""); setAllowance(""); setReason(""); void queryClient.invalidateQueries({ queryKey: ["admin", "quota-tiers"] }); },
  });
  const patch = useMutation({
    mutationFn: ({ tier, archived = false }: { tier: QuotaTier; archived?: boolean }) => unwrap(api.PATCH("/api/admin/quota-tiers/{tier_id}", {
      params: { path: { tier_id: tier.id } },
      body: archived ? { archived: true, reason } : { allowanceMicros: Math.round(Number(edit[tier.id]) * 1_000_000), reason },
    })),
    onSuccess: () => { setReason(""); void queryClient.invalidateQueries({ queryKey: ["admin", "quota-tiers"] }); void queryClient.invalidateQueries({ queryKey: ["admin", "quota-accounts"] }); },
  });
  return <div className="space-y-4 pt-4">
    <Card><CardHeader><CardTitle><h3>Create allowance tier</h3></CardTitle><CardDescription>New tiers use a monthly anchor by default; cadence can be versioned through the API.</CardDescription></CardHeader><CardContent className="grid gap-3 md:grid-cols-[0.7fr_1fr_0.8fr_1.5fr_auto]"><Input aria-label="Tier ID" placeholder="TEAM" value={id} onChange={(event) => setId(event.target.value.toUpperCase())} /><Input aria-label="Tier name" placeholder="Team" value={name} onChange={(event) => setName(event.target.value)} /><Input aria-label="Tier allowance USD" inputMode="decimal" placeholder="USD or blank unlimited" value={allowance} onChange={(event) => setAllowance(event.target.value)} /><Input aria-label="Tier audit reason" placeholder="Audit reason" value={reason} onChange={(event) => setReason(event.target.value)} /><Button disabled={!id || !name || !reason.trim() || create.isPending} onClick={() => create.mutate()}>Create</Button></CardContent></Card>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{tiers.map((tier) => <Card key={tier.id}><CardHeader><div className="flex items-center justify-between"><CardTitle><h3>{tier.name}</h3></CardTitle><Badge variant={tier.isDefault ? "default" : "outline"}>{tier.id}</Badge></div><CardDescription>{tier.cycleCount} {tier.cycleUnit.toLowerCase()} cycle · {tier.memberCount} members</CardDescription></CardHeader><CardContent className="space-y-3"><div className="font-mono text-3xl font-semibold">{usd(tier.allowanceMicros)}</div><div className="flex justify-between text-xs text-muted-foreground"><span>Open-period spend</span><span className="font-mono">{usd(tier.spendMicros)}</span></div><Input aria-label={`${tier.name} allowance USD`} inputMode="decimal" placeholder="New USD allowance" value={edit[tier.id] ?? ""} onChange={(event) => setEdit((value) => ({ ...value, [tier.id]: event.target.value }))} /><div className="flex gap-2"><Button size="sm" variant="outline" disabled={edit[tier.id] === undefined || !reason.trim()} onClick={() => patch.mutate({ tier })}>Apply allowance</Button>{!tier.isDefault ? <Button size="sm" variant="ghost" disabled={!reason.trim()} onClick={() => patch.mutate({ tier, archived: true })}>Archive</Button> : null}</div></CardContent></Card>)}</div>
    <div className="max-w-xl"><Label htmlFor="tier-reason">Reason for tier edits or archive</Label><Input id="tier-reason" className="mt-1" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Required for every tier mutation" /></div>
    {create.isError || patch.isError ? <Alert variant="destructive"><AlertTitle>Tier update failed</AlertTitle><AlertDescription>{create.error?.message ?? patch.error?.message}</AlertDescription></Alert> : null}
  </div>;
}

function RateCreator() {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [effective, setEffective] = useState("");
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/admin/llm-rates", { body: {
      provider, model, contextMinTokens: 0, contextMaxTokens: null,
      inputMicrosPerMillion: Math.round(Number(input) * 1_000_000),
      cacheReadMicrosPerMillion: null, cacheWriteMicrosPerMillion: null,
      outputMicrosPerMillion: Math.round(Number(output) * 1_000_000), toolMicrosPerUnit: null,
      effectiveFrom: new Date(effective).toISOString(), effectiveTo: null, sourceUrl: source, reason,
    } })),
    onSuccess: () => { setProvider(""); setModel(""); setInput(""); setOutput(""); setEffective(""); setSource(""); setReason(""); void queryClient.invalidateQueries({ queryKey: ["admin", "llm-rates"] }); },
  });
  return <Card className="mb-4"><CardHeader><CardTitle><h3>Create future rate version</h3></CardTitle><CardDescription>USD per one million tokens. Overlapping effective ranges are rejected and historical rows cannot be edited.</CardDescription></CardHeader><CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"><Input aria-label="Rate provider" placeholder="anthropic" value={provider} onChange={(event) => setProvider(event.target.value)} /><Input aria-label="Rate model" placeholder="model-id" value={model} onChange={(event) => setModel(event.target.value)} /><Input aria-label="Input rate USD" inputMode="decimal" placeholder="Input USD / 1M" value={input} onChange={(event) => setInput(event.target.value)} /><Input aria-label="Output rate USD" inputMode="decimal" placeholder="Output USD / 1M" value={output} onChange={(event) => setOutput(event.target.value)} /><Input aria-label="Effective from" type="datetime-local" value={effective} onChange={(event) => setEffective(event.target.value)} /><Input aria-label="Pricing source" placeholder="Official pricing URL" value={source} onChange={(event) => setSource(event.target.value)} /><Input aria-label="Rate audit reason" placeholder="Audit reason" value={reason} onChange={(event) => setReason(event.target.value)} /><Button disabled={!provider || !model || !input || !output || !effective || !source || !reason.trim() || create.isPending} onClick={() => create.mutate()}>Create immutable version</Button>{create.isError ? <Alert variant="destructive" className="md:col-span-2 xl:col-span-4"><AlertTitle>Rate version failed</AlertTitle><AlertDescription>{create.error.message}</AlertDescription></Alert> : null}</CardContent></Card>;
}

export function AdminQuotasPage() {
  const me = useMe();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<QuotaAccount | null>(null);
  const [balanceFilter, setBalanceFilter] = useState("");
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
  }), [accounts.data, search, balanceFilter]);
  if (me.isPending) return <Skeleton className="h-80 w-full" />;
  if (me.data?.role !== "admin") return <Navigate to="/" replace />;
  if (summary.isPending || tiers.isPending || accounts.isPending) return <Skeleton className="h-[38rem] w-full" />;
  if (summary.isError || tiers.isError || accounts.isError || !summary.data || !tiers.data || !accounts.data) return <Alert variant="destructive"><AlertTitle>Quota console unavailable</AlertTitle><AlertDescription>{summary.error?.message ?? tiers.error?.message ?? accounts.error?.message}</AlertDescription></Alert>;
  const runway = summary.data.monthlyCapMicros ? (summary.data.monthlySpendMicros / summary.data.monthlyCapMicros) * 100 : 0;
  return (
    <div className="flex flex-col gap-7">
      <PageHeader kicker="Metering console" title="Cost quotas" sub="Control recurring allowances, durable credits, pricing coverage, and audited balance changes." />
      <section aria-label="Platform cost runway" className="rounded-xl border bg-card p-5 shadow-sm">
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5"><Metric label="Month spend" value={usd(summary.data.monthlySpendMicros)} detail="Shared platform keys" /><Metric label="Platform cap" value={usd(summary.data.monthlyCapMicros)} detail="UTC calendar month" /><Metric label="Runway" value={usd(summary.data.remainingMicros)} detail={`${Math.max(0, 100 - runway).toFixed(1)}% remains`} warning={runway >= 80} /><Metric label="Unpriced calls" value={String(summary.data.unpricedCallCount)} detail="Requires rate coverage" warning={summary.data.unpricedCallCount > 0} /><Metric label="Next reset" value={new Date(summary.data.nextResetAt).toLocaleDateString(undefined, { month: "short", day: "numeric" })} detail="00:00 UTC" /></dl>
        <Progress className="mt-5" value={Math.min(100, runway)}><ProgressLabel>Shared-key monthly cap</ProgressLabel><ProgressValue>{() => `${runway.toFixed(1)}%`}</ProgressValue></Progress>
      </section>
      <BulkCommandBar accounts={accounts.data.data} />
      <Tabs defaultValue="members">
        <TabsList variant="line" aria-label="Quota console sections"><TabsTrigger value="members"><Users /> Members</TabsTrigger><TabsTrigger value="tiers"><Layers3 /> Tiers</TabsTrigger><TabsTrigger value="rates"><Gauge /> Rate cards</TabsTrigger><TabsTrigger value="audit"><History /> Audit</TabsTrigger></TabsList>
        <TabsContent value="members" className="space-y-4 pt-4"><div className="flex max-w-xl items-center gap-2"><Search className="size-4 text-muted-foreground" /><Input aria-label="Search members" placeholder="Search member…" value={search} onChange={(event) => setSearch(event.target.value)} /><select aria-label="Balance filter" className="h-9 rounded-lg border bg-background px-2 text-sm" value={balanceFilter} onChange={(event) => setBalanceFilter(event.target.value)}><option value="">All balances</option><option value="POSITIVE">Positive</option><option value="ZERO">Depleted</option><option value="OVERAGE">Overage</option><option value="UNLIMITED">Unlimited</option></select></div><Card><CardContent className="p-0"><Table><TableHeader><TableRow><TableHead>Member</TableHead><TableHead>Tier</TableHead><TableHead>Period spend</TableHead><TableHead>Remaining</TableHead><TableHead>Credits</TableHead><TableHead>Shared / BYOK</TableHead><TableHead>Tokens</TableHead><TableHead>Reset</TableHead></TableRow></TableHeader><TableBody>{filtered.map((account) => <TableRow key={account.userId} className="cursor-pointer" tabIndex={0} onClick={() => setSelected(account)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelected(account); }}><TableCell><div className="font-medium">{account.username}</div>{account.disabled ? <span className="text-xs text-muted-foreground">Disabled</span> : null}</TableCell><TableCell><Badge variant="outline">{account.tierId}</Badge></TableCell><TableCell className="font-mono">{usd(account.spentMicros)}</TableCell><TableCell className="font-mono">{usd(account.remainingMicros)}</TableCell><TableCell className="font-mono">{usd(account.creditBalanceMicros)}</TableCell><TableCell className="font-mono text-xs">{usd(account.sharedCostMicros)} / {usd(account.byokCostMicros)}</TableCell><TableCell className="font-mono">{tokens(account.totalTokens)}</TableCell><TableCell className="text-xs">{new Date(account.periodEnd).toLocaleDateString()}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card></TabsContent>
        <TabsContent value="tiers"><TierPanel tiers={tiers.data.data} /></TabsContent>
        <TabsContent value="rates" className="pt-4"><RateCreator /><Card><CardHeader><CardTitle><h3>Effective rate versions</h3></CardTitle><CardDescription>Historical rows are immutable. Coverage includes exact provider, model, context band, and effective window.</CardDescription></CardHeader><CardContent className="p-0"><Table><TableHeader><TableRow><TableHead>Provider / model</TableHead><TableHead>Context band</TableHead><TableHead>Input</TableHead><TableHead>Cache read / write</TableHead><TableHead>Output</TableHead><TableHead>Tool fee</TableHead><TableHead>Effective</TableHead></TableRow></TableHeader><TableBody>{rates.data?.data.map((rate) => <TableRow key={rate.id}><TableCell><div className="font-medium">{rate.provider}</div><div className="font-mono text-xs text-muted-foreground">{rate.model}</div></TableCell><TableCell className="font-mono text-xs">{tokens(rate.contextMinTokens)}–{rate.contextMaxTokens == null ? "∞" : tokens(rate.contextMaxTokens)}</TableCell><TableCell className="font-mono">{usd(rate.inputMicrosPerMillion)}</TableCell><TableCell className="font-mono text-xs">{usd(rate.cacheReadMicrosPerMillion)} / {usd(rate.cacheWriteMicrosPerMillion)}</TableCell><TableCell className="font-mono">{usd(rate.outputMicrosPerMillion)}</TableCell><TableCell className="font-mono">{usd(rate.toolMicrosPerUnit)}</TableCell><TableCell className="text-xs"><div>{new Date(rate.effectiveFrom).toLocaleDateString()}</div><div className="text-muted-foreground">{rate.effectiveTo ? `to ${new Date(rate.effectiveTo).toLocaleDateString()}` : "active"}</div></TableCell></TableRow>)}</TableBody></Table></CardContent></Card></TabsContent>
        <TabsContent value="audit" className="pt-4"><Card><CardHeader><CardTitle><h3>Quota operation ledger</h3></CardTitle><CardDescription>Actor, scope, reason, affected count, and timestamp for every committed bulk operation.</CardDescription></CardHeader><CardContent className="p-0"><Table><TableHeader><TableRow><TableHead>Action</TableHead><TableHead>Scope</TableHead><TableHead>Amount</TableHead><TableHead>Affected</TableHead><TableHead>Reason</TableHead><TableHead>Timestamp</TableHead></TableRow></TableHeader><TableBody>{operations.data?.data.map((operation) => <TableRow key={operation.id}><TableCell><Badge variant="outline">{operation.actionType.replaceAll("_", " ")}</Badge></TableCell><TableCell>{operation.targetType}</TableCell><TableCell className="font-mono">{usd(operation.amountMicros)}</TableCell><TableCell>{operation.affectedCount}</TableCell><TableCell className="max-w-xs">{operation.reason}</TableCell><TableCell className="text-xs"><Clock3 className="mr-1 inline size-3" />{new Date(operation.createdAt).toLocaleString()}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card></TabsContent>
      </Tabs>
      <AccountDrawer account={selected} open={selected != null} onOpenChange={(open) => { if (!open) setSelected(null); }} />
    </div>
  );
}
