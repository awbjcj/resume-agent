import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import i18n from "@/i18n";
import type { components } from "@/lib/api/schema";
import { axisProps, CHART_COLORS, tooltipProps } from "./chart-theme";

type Offer = components["schemas"]["OfferOut"];

function localized(t: TFunction | undefined, key: string): string {
  return t ? t(key) : i18n.t(key);
}

export function toOfferRows(offers: Offer[], t?: TFunction) {
  const fallback = localized(t, "analytics.offer.fallback");
  return offers.map((offer) => ({
    company: offer.company || fallback,
    label: `${offer.company || fallback} · #${offer.sequence}`,
    base: offer.compBase ?? 0,
    bonus: offer.compBonus ?? 0,
    equity: offer.compEquityAnnual ?? 0,
    signing: offer.compSigning ?? 0,
    currency: offer.compCurrency || localized(t, "analytics.offer.unspecifiedCurrency"),
  }));
}

export function OfferComparisonChart({ offers }: { offers: Offer[] }) {
  const { t } = useTranslation();
  if (offers.length === 0) return null;
  const rows = toOfferRows(offers, t);
  const currencies = [...new Set(rows.map((row) => row.currency))];
  return (
    <div className="space-y-6">
      {currencies.length > 1 ? (
        <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
          Mixed currencies are shown in separate panels; no currency conversion is implied.
        </p>
      ) : null}
      {currencies.map((currency) => {
        const currencyRows = rows.filter((row) => row.currency === currency);
        return (
          <section key={currency} aria-label={t("analytics.offer.currencyOffers", { currency })}>
            <h4 className="mb-2 text-sm font-medium">{currency}</h4>
            <div className="h-72 min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={currencyRows} margin={{ left: 8, right: 16 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="label" {...axisProps} />
                  <YAxis {...axisProps} tickFormatter={(value) => `${Math.round(Number(value) / 1000)}k`} />
                  <Tooltip {...tooltipProps} formatter={(value) => [`${Number(value).toLocaleString()} ${currency}`]} />
                  <Legend />
                  <Bar dataKey="base" name={t("analytics.offer.base")} stackId="comp" fill={CHART_COLORS.categorical[0]} />
                  <Bar dataKey="bonus" name={t("analytics.offer.bonus")} stackId="comp" fill={CHART_COLORS.categorical[1]} />
                  <Bar dataKey="equity" name={t("analytics.offer.equityAnnual")} stackId="comp" fill={CHART_COLORS.categorical[2]} />
                  <Bar dataKey="signing" name={t("analytics.offer.signing")} stackId="comp" fill={CHART_COLORS.categorical[3]} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        );
      })}
    </div>
  );
}
