import { useEffect, useState } from "react";

// Mirrors tenancy/costs.py::_PEAK_HOUR_BANDS and _rate_period exactly — a
// published DeepSeek schedule, not app config, so it is safe to restate here
// rather than round-trip the server for a clock computation. If DeepSeek's
// windows ever change, update both this file and costs.py together.
const PEAK_HOUR_BANDS: readonly [number, number][] = [
  [1, 4],
  [6, 10],
];
// tenancy/costs.py::seed_llm_rates's deepseek_price_update — the moment
// DeepSeek's flat rate is replaced by this peak/off-peak schedule. Before it,
// there is nothing time-varying to show.
const CUTOVER_UTC = new Date("2026-08-16T16:00:00Z");
// From Saturday 2026-08-29 00:00 Beijing time, all Saturday/Sunday requests are
// billed at the off-peak rate. The conversion is fixed at UTC+8: Beijing has
// no daylight-saving transition to account for.
const WEEKEND_OFF_PEAK_FROM_UTC = new Date("2026-08-28T16:00:00Z");
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1_000;

export type RatePeriod = "peak" | "off_peak";

export type DeepSeekPricingStatus = {
  period: RatePeriod;
  /** The next moment the period flips. */
  changesAt: Date;
  /** The moment this status was computed — render must derive countdowns
   * from this rather than calling Date.now() itself, which would make the
   * component impure. */
  now: Date;
  /** True when the Beijing-time weekend keeps the entire day off-peak. */
  weekendOffPeak: boolean;
};

function isPeakHour(hour: number): boolean {
  return PEAK_HOUR_BANDS.some(([start, end]) => hour >= start && hour < end);
}

function isBeijingWeekend(now: Date): boolean {
  const beijing = new Date(now.getTime() + BEIJING_OFFSET_MS);
  const day = beijing.getUTCDay();
  return day === 0 || day === 6;
}

function usesWeekendOffPeak(now: Date): boolean {
  return now >= WEEKEND_OFF_PEAK_FROM_UTC && isBeijingWeekend(now);
}

function periodAt(now: Date): RatePeriod {
  if (usesWeekendOffPeak(now)) return "off_peak";
  return isPeakHour(now.getUTCHours()) ? "peak" : "off_peak";
}

function nextBoundary(now: Date): Date {
  const currentPeriod = periodAt(now);
  const changesAt = new Date(now);
  changesAt.setUTCMinutes(0, 0, 0);
  changesAt.setUTCHours(changesAt.getUTCHours() + 1);

  // The schedule only changes on an hour boundary. Scanning a little over a
  // week covers every weekday/weekend transition without hard-coding a local
  // date calculation that could drift from the pricing rules above.
  for (let hour = 0; hour < 8 * 24; hour += 1) {
    if (periodAt(changesAt) !== currentPeriod) return changesAt;
    changesAt.setUTCHours(changesAt.getUTCHours() + 1);
  }

  return changesAt;
}

export function getDeepSeekPricingStatus(now: Date): DeepSeekPricingStatus | null {
  if (now < CUTOVER_UTC) return null;
  return {
    period: periodAt(now),
    changesAt: nextBoundary(now),
    now,
    weekendOffPeak: usesWeekendOffPeak(now),
  };
}

export function formatCountdown(ms: number): string {
  const totalMinutes = Math.max(0, Math.round(ms / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

export function formatUtcClock(date: Date): string {
  return `${String(date.getUTCHours()).padStart(2, "0")}:${String(
    date.getUTCMinutes(),
  ).padStart(2, "0")}`;
}

// A 30s tick is far finer than this ever needs (transitions land on the
// hour), but cheap enough to keep the countdown feeling current without any
// visible catch-up jump.
const TICK_MS = 30_000;

export function useDeepSeekPricingStatus(): DeepSeekPricingStatus | null {
  const [status, setStatus] = useState(() => getDeepSeekPricingStatus(new Date()));
  useEffect(() => {
    const tick = () => setStatus(getDeepSeekPricingStatus(new Date()));
    tick();
    const id = setInterval(tick, TICK_MS);
    return () => clearInterval(id);
  }, []);
  return status;
}
