import { CalendarDays, CalendarPlus, MapPin } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { KIND_LABELS, REPEATABLE_KINDS } from "@/features/job/event-labels";
import { openDownload } from "@/lib/api/client";
import { formatCalendarDate } from "@/lib/calendar-date";
import type { DashboardSummary } from "./use-dashboard-summary";

type UpcomingEvent = NonNullable<DashboardSummary["upcomingEvents"]>[number];

function eventTitle(event: UpcomingEvent, otherLabel: string): string {
  const label = event.kind === "custom"
    ? event.customLabel || otherLabel
    : KIND_LABELS[event.kind] ?? event.kind;
  return REPEATABLE_KINDS.has(event.kind) ? `${label} ${event.sequence}` : label;
}

function eventTime(event: UpcomingEvent, locale: string): string {
  const date = new Date(event.occurredAt);
  const options: Intl.DateTimeFormatOptions = event.allDay
    ? { weekday: "short", month: "short", day: "numeric" }
    : {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZone: event.timezone ?? undefined,
        timeZoneName: event.timezone ? "short" : undefined,
      };
  try {
    return formatCalendarDate(event.occurredAt, event.allDay, options, locale);
  } catch {
    return date.toLocaleString(locale);
  }
}

export function UpcomingCard({ events }: { events: UpcomingEvent[] }) {
  const { t, i18n } = useTranslation();
  if (events.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarDays className="size-4 text-primary" aria-hidden="true" />
          <h2>{t("dashboard.nextSevenDays")}</h2>
        </CardTitle>
        <CardDescription>{t("dashboard.upcomingDescription")}</CardDescription>
        <CardAction>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void openDownload("/api/applications/upcoming.ics").catch((error: Error) =>
                toast.error(error.message),
              );
            }}
          >
            <CalendarPlus aria-hidden="true" />
            {t("dashboard.downloadCalendar")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <ol className="divide-y rounded-lg border bg-background">
          {events.map((event) => {
            const company = event.company || t("dashboard.application");
            const role = event.title ? ` · ${event.title}` : "";
            return (
              <li
                key={event.eventId}
                className="grid min-w-0 gap-3 p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <p className="font-heading font-medium">{eventTitle(event, t("dashboard.otherEvent"))}</p>
                  <p className="mt-1 truncate text-sm text-muted-foreground">
                    {company}{role}
                  </p>
                  <p className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                    <CalendarDays className="size-3.5 shrink-0" aria-hidden="true" />
                    <span>{eventTime(event, i18n.resolvedLanguage ?? i18n.language)}</span>
                    {event.locationOrLink ? (
                      <>
                        <span aria-hidden="true">·</span>
                        <MapPin className="size-3.5 shrink-0" aria-hidden="true" />
                        <span className="truncate">{event.locationOrLink}</span>
                      </>
                    ) : null}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  render={<Link to={`/pipeline?job=${event.jobId}`} />}
                >
                  {t("dashboard.viewCompany", { company })}
                </Button>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
