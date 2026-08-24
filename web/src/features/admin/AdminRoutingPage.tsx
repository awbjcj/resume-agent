import { useMemo, useState } from "react";
import { Cable, KeyRound, Network } from "lucide-react";
import { Navigate, Link } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { SaveBar } from "@/features/settings/SaveBar";
import { useMe } from "@/features/auth/AuthGate";
import type { components } from "@/lib/api/schema";
import { useAdminRouting, useSaveAdminRouting } from "./use-admin-routing";

type RouteMode = components["schemas"]["RoutingUpdate"]["anthropicRouteMode"];
type RoutingDoc = components["schemas"]["RoutingConfigDoc"];
type Draft = {
  baseUrl: string;
  modes: Record<string, RouteMode>;
  keys: Record<string, string | null | undefined>;
};

const MODE_COPY: Record<Exclude<RouteMode, null | undefined>, string> = {
  auto: "Use the subscription gateway when its key is configured; otherwise use the direct API.",
  subscription: "Require the gateway. Incomplete configuration fails before a paid API call can start.",
  api: "Always use the provider's direct metered API and ignore its gateway key.",
};

function draftFrom(doc: RoutingDoc): Draft {
  return {
    baseUrl: doc.baseUrl,
    modes: Object.fromEntries(doc.providers.map((provider) => [provider.provider, provider.routeMode])),
    keys: {},
  };
}

export function AdminRoutingPage() {
  const me = useMe();
  const routing = useAdminRouting(me.data?.role === "admin");
  const save = useSaveAdminRouting();
  const [draftOverride, setDraft] = useState<Draft | null>(null);
  const draft = draftOverride ?? (routing.data ? draftFrom(routing.data) : null);

  const dirty = useMemo(() => {
    if (!draft || !routing.data) return false;
    return (
      draft.baseUrl !== routing.data.baseUrl ||
      routing.data.providers.some((provider) => draft.modes[provider.provider] !== provider.routeMode) ||
      Object.values(draft.keys).some((value) => value !== undefined)
    );
  }, [draft, routing.data]);

  if (me.isPending) return <Skeleton className="h-80 w-full" />;
  if (me.data?.role !== "admin") return <Navigate to="/" replace />;
  if (routing.isPending || !draft) return <Skeleton className="h-[36rem] w-full" />;
  if (routing.isError || !routing.data) {
    return <Alert variant="destructive"><AlertTitle>Routing is unavailable</AlertTitle><AlertDescription>{routing.error?.message ?? "Please try again."}</AlertDescription></Alert>;
  }

  const submit = () => {
    const body: Record<string, unknown> = { baseUrl: draft.baseUrl };
    for (const provider of routing.data.providers) {
      body[`${provider.provider}RouteMode`] = draft.modes[provider.provider];
      const key = draft.keys[provider.provider];
      if (key !== undefined) body[`${provider.provider}Key`] = key;
    }
    save.mutate(body as never, { onSuccess: () => setDraft(null) });
  };

  return (
    <div className="flex flex-col gap-8">
      <PageHeader kicker="LLM infrastructure" title="Provider routing" sub="Choose which providers use your subscription gateway and which stay on their direct metered APIs." />
      <nav aria-label="Administration sections" className="-mt-5 flex flex-wrap gap-2">
        <Button nativeButton={false} variant="outline" size="sm" render={<Link to="/admin" />}>Access &amp; data</Button>
        <Button nativeButton={false} variant="outline" size="sm" render={<Link to="/admin/quotas" />}>Cost quotas</Button>
        <Button variant="secondary" size="sm">Provider routing</Button>
      </nav>

      <Alert className="-mt-5">
        <Network aria-hidden="true" />
        <AlertTitle>Endpoint and credential move together</AlertTitle>
        <AlertDescription>Subscription calls are quota-exempt and report zero marginal spend. A provider pinned to subscription will fail loudly if its URL or key is missing.</AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="border-b"><CardTitle><h2 className="flex items-center gap-2"><Cable className="size-4" aria-hidden="true" />Gateway</h2></CardTitle></CardHeader>
        <CardContent>
          <Field>
            <FieldLabel htmlFor="sub2api-base-url">Sub2API base URL</FieldLabel>
            <Input id="sub2api-base-url" type="url" value={draft.baseUrl} placeholder="https://sub2api.example.com" onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} />
            <FieldDescription>Enter the public origin only. Provider-specific API paths are added by the server.</FieldDescription>
          </Field>
        </CardContent>
      </Card>

      <section aria-labelledby="provider-routes" className="flex flex-col gap-4">
        <div><h2 id="provider-routes" className="text-lg font-semibold">Provider routes</h2><p className="text-sm text-muted-foreground">Keys are write-only; saved credentials display only their final four characters.</p></div>
        <div className="grid gap-4 lg:grid-cols-2">
          {routing.data.providers.map((provider) => {
            const mode = draft.modes[provider.provider] ?? "auto";
            const keyValue = draft.keys[provider.provider];
            return (
              <Card key={provider.provider}>
                <CardHeader className="border-b"><div className="flex items-center justify-between gap-3"><CardTitle><h3>{provider.label}</h3></CardTitle><Badge variant={provider.configurationError ? "destructive" : provider.effectiveMode === "subscription" ? "default" : "outline"}>{provider.configurationError ? "Needs attention" : provider.effectiveMode === "subscription" ? "Subscription" : "Direct API"}</Badge></div></CardHeader>
                <CardContent className="flex flex-col gap-5">
                  {provider.configurationError ? <Alert variant="destructive"><AlertTitle>Configuration incomplete</AlertTitle><AlertDescription>{provider.configurationError}</AlertDescription></Alert> : null}
                  <Field>
                    <FieldLabel htmlFor={`${provider.provider}-route-mode`}>Route mode</FieldLabel>
                    <Select value={mode ?? "auto"} onValueChange={(value) => setDraft({ ...draft, modes: { ...draft.modes, [provider.provider]: value as RouteMode } })}>
                      <SelectTrigger id={`${provider.provider}-route-mode`} aria-label={`${provider.label} route mode`} className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>{(["auto", "subscription", "api"] as const).map((value) => <SelectItem key={value} value={value}>{value === "api" ? "Direct API" : value[0].toUpperCase() + value.slice(1)}</SelectItem>)}</SelectContent>
                    </Select>
                    <FieldDescription>{MODE_COPY[mode ?? "auto"]}</FieldDescription>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor={`${provider.provider}-gateway-key`}>Gateway key</FieldLabel>
                    <Input id={`${provider.provider}-gateway-key`} type="password" autoComplete="new-password" value={keyValue ?? ""} placeholder={provider.key.isSet ? `Configured ····${provider.key.hint ?? ""}` : "Not configured"} onChange={(event) => setDraft({ ...draft, keys: { ...draft.keys, [provider.provider]: event.target.value } })} />
                    <div className="flex items-center justify-between gap-3"><FieldDescription>{keyValue === null ? "This key will be cleared when you save." : "Leave blank to keep the saved key unchanged."}</FieldDescription>{provider.key.isSet && keyValue !== null ? <Button type="button" variant="ghost" size="sm" onClick={() => setDraft({ ...draft, keys: { ...draft.keys, [provider.provider]: null } })}><KeyRound data-icon="inline-start" />Clear key</Button> : null}</div>
                  </Field>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      {save.isError ? <Alert variant="destructive"><AlertTitle>Routing could not be saved</AlertTitle><AlertDescription>{save.error.message}</AlertDescription></Alert> : null}
      <SaveBar dirty={dirty} saving={save.isPending} onSave={submit} onDiscard={() => setDraft(null)} />
    </div>
  );
}
