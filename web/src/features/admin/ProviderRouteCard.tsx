import { AlertTriangle, Globe, KeyRound, Undo2, Waypoints } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { components } from "@/lib/api/schema";

type ProviderStatus = components["schemas"]["ProviderRoutingStatus"];
export type RouteMode = ProviderStatus["routeMode"];

/**
 * The single source for every place a route mode is named: the closed select
 * trigger, the option list, and the explanation under it. Passing this array to
 * the Select root also pre-populates Base UI's label store, so the trigger shows
 * "Direct API" on first paint instead of the raw value "api".
 */
export const ROUTE_MODES: ReadonlyArray<{
  value: RouteMode;
  label: string;
  description: string;
}> = [
  {
    value: "auto",
    label: "Auto",
    description:
      "Use the subscription gateway when its key is configured; otherwise use the direct API.",
  },
  {
    value: "subscription",
    label: "Subscription",
    description:
      "Require the gateway. Incomplete configuration fails before a paid API call can start.",
  },
  {
    value: "api",
    label: "Direct API",
    description: "Always use the provider's direct metered API and ignore its gateway key.",
  },
];

const modeCopy = (mode: RouteMode) => ROUTE_MODES.find((entry) => entry.value === mode) ?? ROUTE_MODES[0];

/** Status is derived once so the badge's wording, colour, and icon can never disagree. */
function routeStatus(provider: ProviderStatus) {
  if (provider.configurationError) {
    return { label: "Needs attention", variant: "destructive" as const, Icon: AlertTriangle };
  }
  if (provider.effectiveMode === "subscription") {
    return { label: "Subscription", variant: "default" as const, Icon: Waypoints };
  }
  return { label: "Direct API", variant: "outline" as const, Icon: Globe };
}

export function ProviderRouteCard({
  provider,
  mode,
  keyDraft,
  gatewayHost,
  onModeChange,
  onKeyChange,
}: {
  provider: ProviderStatus;
  mode: RouteMode;
  keyDraft: string | null | undefined;
  gatewayHost: string;
  onModeChange: (mode: RouteMode) => void;
  onKeyChange: (value: string | null | undefined) => void;
}) {
  const status = routeStatus(provider);
  const clearing = keyDraft === null;
  const edited = mode !== provider.routeMode || keyDraft !== undefined;
  const keyId = `${provider.provider}-gateway-key`;

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>
              <h3>{provider.label}</h3>
            </CardTitle>
            {/* Where this provider's traffic goes right now, and what it costs —
                the one question the page exists to answer. */}
            <CardDescription className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs">
              {provider.effectiveMode === "subscription" ? (
                <>
                  <span className="font-mono">{gatewayHost || "gateway"}</span>
                  <span>· quota-exempt</span>
                </>
              ) : (
                <span>Provider API · metered spend</span>
              )}
              {edited ? <span className="text-primary">· unsaved</span> : null}
            </CardDescription>
          </div>
          <Badge variant={status.variant}>
            <status.Icon data-icon="inline-start" aria-hidden="true" />
            {status.label}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-5">
        {provider.configurationError ? (
          <Alert variant="destructive">
            <AlertTriangle aria-hidden="true" />
            <AlertTitle>Configuration incomplete</AlertTitle>
            <AlertDescription>{provider.configurationError}</AlertDescription>
          </Alert>
        ) : null}

        <Field>
          <FieldLabel htmlFor={`${provider.provider}-route-mode`}>Route mode</FieldLabel>
          <Select
            items={ROUTE_MODES}
            value={mode}
            onValueChange={(value) => onModeChange(value as RouteMode)}
          >
            <SelectTrigger
              id={`${provider.provider}-route-mode`}
              aria-label={`${provider.label} route mode`}
              className="w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROUTE_MODES.map((entry) => (
                <SelectItem key={entry.value} value={entry.value}>
                  {entry.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* Reserve the taller of the three explanations so switching modes
              cannot shuffle the cards below it. */}
          <FieldDescription className="min-h-10">{modeCopy(mode).description}</FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor={keyId}>Gateway key</FieldLabel>
          <Input
            id={keyId}
            type="password"
            autoComplete="new-password"
            disabled={clearing}
            value={keyDraft ?? ""}
            placeholder={
              clearing
                ? "Cleared on save"
                : provider.key.isSet
                  ? `Configured ····${provider.key.hint ?? ""}`
                  : "Not configured"
            }
            onChange={(event) => onKeyChange(event.target.value)}
          />
          <div className="flex min-h-9 items-center justify-between gap-3">
            <FieldDescription aria-live="polite">
              {clearing
                ? "This key will be cleared when you save."
                : "Leave blank to keep the saved key unchanged."}
            </FieldDescription>
            {clearing ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => onKeyChange(undefined)}>
                <Undo2 data-icon="inline-start" />
                Keep key
              </Button>
            ) : provider.key.isSet ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => onKeyChange(null)}>
                <KeyRound data-icon="inline-start" />
                Clear key
              </Button>
            ) : null}
          </div>
        </Field>
      </CardContent>
    </Card>
  );
}
