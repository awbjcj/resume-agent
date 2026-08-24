import { useMemo, useState } from "react";
import { Cable, Network } from "lucide-react";
import { Navigate } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { SaveBar } from "@/features/settings/SaveBar";
import { useMe } from "@/features/auth/AuthGate";
import type { components } from "@/lib/api/schema";
import { AdminSectionNav } from "./AdminSectionNav";
import { ProviderRouteCard, type RouteMode } from "./ProviderRouteCard";
import { useAdminRouting, useSaveAdminRouting } from "./use-admin-routing";

type RoutingDoc = components["schemas"]["RoutingConfigDoc"];
type Draft = {
  baseUrl: string;
  modes: Record<string, RouteMode>;
  keys: Record<string, string | null | undefined>;
};

function draftFrom(doc: RoutingDoc): Draft {
  return {
    baseUrl: doc.baseUrl,
    modes: Object.fromEntries(doc.providers.map((provider) => [provider.provider, provider.routeMode])),
    keys: {},
  };
}

/** Show the operator the host their traffic actually reaches, not the raw field text. */
function hostOf(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed).host;
  } catch {
    return trimmed;
  }
}

function RoutingSkeleton() {
  return (
    <div className="flex flex-col gap-8" aria-busy="true" aria-label="Loading provider routing">
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-32 w-full" />
      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-72 w-full" />
        ))}
      </div>
    </div>
  );
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
  if (routing.isError || !routing.data) {
    if (routing.isPending) return <RoutingSkeleton />;
    return (
      <Alert variant="destructive">
        <AlertTitle>Routing is unavailable</AlertTitle>
        <AlertDescription>{routing.error?.message ?? "Please try again."}</AlertDescription>
      </Alert>
    );
  }
  if (!draft) return <RoutingSkeleton />;

  const providers = routing.data.providers;
  const onGateway = providers.filter((provider) => provider.effectiveMode === "subscription").length;
  // The card lines describe the route as it is saved today, so they stay in step
  // with each provider's effective mode while an edit is still pending.
  const gatewayHost = hostOf(routing.data.baseUrl);

  const submit = () => {
    const body: Record<string, unknown> = { baseUrl: draft.baseUrl };
    for (const provider of providers) {
      body[`${provider.provider}RouteMode`] = draft.modes[provider.provider];
      const key = draft.keys[provider.provider];
      if (key !== undefined) body[`${provider.provider}Key`] = key;
    }
    save.mutate(body as never, { onSuccess: () => setDraft(null) });
  };

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        kicker="LLM infrastructure"
        title="Provider routing"
        sub="Choose which providers use your subscription gateway and which stay on their direct metered APIs."
      />
      <AdminSectionNav current="/admin/routing" />

      <Alert className="-mt-5">
        <Network aria-hidden="true" />
        <AlertTitle>Endpoint and credential move together</AlertTitle>
        <AlertDescription>
          Subscription calls are quota-exempt and report zero marginal spend. A provider pinned to
          subscription will fail loudly if its URL or key is missing.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="border-b">
          <CardTitle>
            <h2 className="flex items-center gap-2">
              <Cable className="size-4" aria-hidden="true" />
              Gateway
            </h2>
          </CardTitle>
          <CardDescription>
            {onGateway} of {providers.length} providers currently route through it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Field>
            <FieldLabel htmlFor="sub2api-base-url">Sub2API base URL</FieldLabel>
            <Input
              id="sub2api-base-url"
              type="url"
              value={draft.baseUrl}
              placeholder="https://sub2api.example.com"
              onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })}
            />
            <FieldDescription>
              Enter the public origin only. Provider-specific API paths are added by the server.
            </FieldDescription>
          </Field>
        </CardContent>
      </Card>

      <section aria-labelledby="provider-routes" className="flex flex-col gap-4">
        <div>
          <h2 id="provider-routes" className="text-lg font-semibold">
            Provider routes
          </h2>
          <p className="text-sm text-muted-foreground">
            Keys are write-only; saved credentials display only their final four characters.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {providers.map((provider) => (
            <ProviderRouteCard
              key={provider.provider}
              provider={provider}
              mode={draft.modes[provider.provider] ?? provider.routeMode}
              keyDraft={draft.keys[provider.provider]}
              gatewayHost={gatewayHost}
              onModeChange={(mode) =>
                setDraft({ ...draft, modes: { ...draft.modes, [provider.provider]: mode } })
              }
              onKeyChange={(value) =>
                setDraft({ ...draft, keys: { ...draft.keys, [provider.provider]: value } })
              }
            />
          ))}
        </div>
      </section>

      {save.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Routing could not be saved</AlertTitle>
          <AlertDescription>{save.error.message}</AlertDescription>
        </Alert>
      ) : null}
      <SaveBar dirty={dirty} saving={save.isPending} onSave={submit} onDiscard={() => setDraft(null)} />
    </div>
  );
}
