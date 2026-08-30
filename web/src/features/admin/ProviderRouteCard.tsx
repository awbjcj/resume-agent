import { AlertTriangle, Globe, KeyRound, Undo2, Waypoints } from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

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

function configurationErrorLabel(t: TFunction, error: string): string {
  const subscription = /^(.+) is pinned to subscription mode but ([A-Z0-9_]+) is unset$/.exec(error);
  if (subscription) {
    const [, provider, setting] = subscription;
    return setting === "SUB2API_BASE_URL"
      ? t("providerRouting.errors.subscriptionBaseUrlUnset", { provider })
      : t("providerRouting.errors.subscriptionKeyUnset", { provider, setting });
  }
  const keyWithoutBaseUrl = /^([A-Z0-9_]+) is set but SUB2API_BASE_URL is unset, so there is nowhere to send the call$/.exec(error);
  if (keyWithoutBaseUrl) return t("providerRouting.errors.keyWithoutBaseUrl", { setting: keyWithoutBaseUrl[1] });
  const invalidBaseUrl = /^([A-Z0-9_]+) must be an absolute http\(s\) URL with no credentials, query, or fragment \(got (.+)\)$/.exec(error);
  if (invalidBaseUrl) return t("providerRouting.errors.invalidBaseUrl", { setting: invalidBaseUrl[1], value: invalidBaseUrl[2] });
  return error;
}

/**
 * The single source for every place a route mode is named: the closed select
 * trigger, the option list, and the explanation under it. Passing this array to
 * the Select root also pre-populates Base UI's label store, so the trigger shows
 * a localized label on first paint instead of the raw value "api".
 */
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
  const { t } = useTranslation();
  const routeModes = [
    {
      value: "auto" as const,
      label: t("providerRouting.modes.auto.label"),
      description: t("providerRouting.modes.auto.description"),
    },
    {
      value: "subscription" as const,
      label: t("providerRouting.modes.subscription.label"),
      description: t("providerRouting.modes.subscription.description"),
    },
    {
      value: "api" as const,
      label: t("providerRouting.modes.api.label"),
      description: t("providerRouting.modes.api.description"),
    },
  ] satisfies ReadonlyArray<{ value: RouteMode; label: string; description: string }>;
  const modeCopy = routeModes.find((entry) => entry.value === mode) ?? routeModes[0];
  const status = provider.configurationError
    ? { label: t("providerRouting.status.needsAttention"), variant: "destructive" as const, Icon: AlertTriangle }
    : provider.effectiveMode === "subscription"
      ? { label: t("providerRouting.status.subscription"), variant: "default" as const, Icon: Waypoints }
      : { label: t("providerRouting.status.api"), variant: "outline" as const, Icon: Globe };
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
                  <span className="font-mono">{gatewayHost || t("providerRouting.gatewayFallback")}</span>
                  <span>· {t("providerRouting.summary.quotaExempt")}</span>
                </>
              ) : (
                <span>{t("providerRouting.summary.apiMetered")}</span>
              )}
              {edited ? <span className="text-primary">· {t("providerRouting.summary.unsaved")}</span> : null}
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
            <AlertDescription>{configurationErrorLabel(t, provider.configurationError)}</AlertDescription>
          </Alert>
        ) : null}

        <Field>
          <FieldLabel htmlFor={`${provider.provider}-route-mode`}>Route mode</FieldLabel>
          <Select
            items={routeModes}
            value={mode}
            onValueChange={(value) => onModeChange(value as RouteMode)}
          >
            <SelectTrigger
              id={`${provider.provider}-route-mode`}
              aria-label={t("providerRouting.routeModeFor", { provider: provider.label })}
              className="w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {routeModes.map((entry) => (
                <SelectItem key={entry.value} value={entry.value}>
                  {entry.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* Reserve the taller of the three explanations so switching modes
              cannot shuffle the cards below it. */}
          <FieldDescription className="min-h-10">{modeCopy.description}</FieldDescription>
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
