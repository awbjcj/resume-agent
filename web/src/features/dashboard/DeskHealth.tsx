import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useSetupStatus,
  type SetupStatus,
} from "@/features/settings/use-setup-status";

type HealthItem = {
  key: string;
  label: string;
  labelKey: `dashboard.health.${"apiKey" | "resume" | "facts" | "search" | "sources"}`;
  to: string;
  ok: (s: SetupStatus) => boolean;
};

export const HEALTH_ITEMS: HealthItem[] = [
  {
    key: "key",
    label: "LLM API key",
    labelKey: "dashboard.health.apiKey",
    to: "/settings/keys",
    // Readiness is provider-agnostic (anyLlmKey), matching the backend's
    // any_llm_key gate — a working OpenAI/Gemini/DeepSeek setup must not be
    // perpetually flagged as missing an Anthropic key.
    ok: (s) => s.secrets.anyLlmKey,
  },
  {
    key: "resume",
    label: "Resume document",
    labelKey: "dashboard.health.resume",
    to: "/profile",
    ok: (s) => s.profile.hasResume,
  },
  {
    key: "facts",
    label: "Profile facts built",
    labelKey: "dashboard.health.facts",
    to: "/profile",
    ok: (s) => s.profile.factsBuiltAt != null,
  },
  {
    key: "search",
    label: "Search configured",
    labelKey: "dashboard.health.search",
    to: "/settings/search",
    ok: (s) => s.search.configured,
  },
  {
    key: "sources",
    label: "Sources enabled",
    labelKey: "dashboard.health.sources",
    to: "/settings/sources",
    ok: (s) => s.sources.enabledCount > 0,
  },
];

export function DeskHealth() {
  const { t } = useTranslation();
  const { data: status, isError, isPending } = useSetupStatus();
  // Fail-open: a broken status endpoint must not break the dashboard (spec §7).
  if (isPending || isError || !status) return null;
  const allOk = HEALTH_ITEMS.every((item) => item.ok(status));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {t("dashboard.deskHealth")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {allOk ? (
          <p className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="size-4 text-primary" aria-hidden="true" />
            {t("dashboard.deskReady")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {HEALTH_ITEMS.map((item) => {
              const ok = item.ok(status);
              return (
                <li key={item.key} className="flex items-center gap-2 text-sm">
                  {ok ? (
                    <CheckCircle2
                      className="size-4 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                  ) : (
                    <AlertCircle
                      className="size-4 shrink-0 text-destructive"
                      aria-hidden="true"
                    />
                  )}
                  {ok ? (
                    <span className="text-muted-foreground">{t(item.labelKey)}</span>
                  ) : (
                    <Link
                      to={item.to}
                      className="underline-offset-4 hover:underline"
                    >
                      {t(item.labelKey)}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {!status.complete && (
          <Link
            to="/setup"
            className="mt-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t("dashboard.resumeSetup")}
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
