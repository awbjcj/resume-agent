import { CalendarClock, CalendarPlus, MapPin, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { openDownload } from "@/lib/api/client";
import { formatCalendarDate } from "@/lib/calendar-date";
import { EventFormDialog } from "./EventFormDialog";
import {
  KIND_LABELS,
  MODALITY_LABELS,
  PLATFORM_LABELS,
  REPEATABLE_KINDS,
  RESULT_LABELS,
} from "./event-labels";
import {
  useDeleteEvent,
  useUpdateEvent,
  type ApplicationEvent,
} from "./use-application-events";

function titleFor(event: ApplicationEvent): string {
  if (event.kind === "custom") return event.customLabel || "Other";
  const label = KIND_LABELS[event.kind] ?? event.kind;
  return REPEATABLE_KINDS.has(event.kind) ? `${label} ${event.sequence}` : label;
}

function formatDate(event: ApplicationEvent): string {
  if (!event.occurredAt) return "No date";
  const moment = new Date(event.occurredAt);
  const options: Intl.DateTimeFormatOptions = event.allDay
    ? { month: "short", day: "numeric", year: "numeric" }
    : {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZone: event.timezone ?? undefined,
        timeZoneName: event.timezone ? "short" : undefined,
      };
  try {
    return formatCalendarDate(event.occurredAt, event.allDay, options);
  } catch {
    return moment.toLocaleString();
  }
}

function isWebLink(value: string | null | undefined): value is string {
  if (!value) return false;
  try {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

export function EventRow({ event, jobId, now }: { event: ApplicationEvent; jobId: number; now?: Date }) {
  const update = useUpdateEvent(jobId, event.id);
  const remove = useDeleteEvent(jobId, event.id);
  const [renderedAt] = useState(() => new Date());
  const upcoming = event.occurredAt ? new Date(event.occurredAt).getTime() > (now ?? renderedAt).getTime() : false;
  const platform = event.platform === "other"
    ? event.platformOther
    : event.platform
      ? PLATFORM_LABELS[event.platform] ?? event.platform
      : null;
  const meta = [
    event.modality ? MODALITY_LABELS[event.modality] ?? event.modality : null,
    platform,
    event.durationMinutes ? `${event.durationMinutes} min` : null,
    event.interviewers,
  ].filter(Boolean);

  return (
    <li className="relative pl-7">
      <span
        className="absolute left-[0.18rem] top-2 size-2.5 rounded-full border-2 border-background bg-primary ring-2 ring-primary/20"
        aria-hidden="true"
      />
      <article className="rounded-xl border bg-card p-4 shadow-card transition-[border-color,box-shadow] duration-150 ease-out-strong hover:border-foreground/20 hover:shadow-card-raised">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="font-heading text-sm font-semibold">{titleFor(event)}</h4>
              {upcoming && <Badge variant="secondary">Upcoming</Badge>}
              <Badge variant="outline">{RESULT_LABELS[event.result] ?? event.result}</Badge>
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <CalendarClock className="size-3.5" aria-hidden="true" />
              {formatDate(event)}
            </p>
          </div>
          <div className="flex items-center gap-1">
            {event.occurredAt && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Add ${titleFor(event)} to calendar`}
                onClick={() => {
                  void openDownload(`/api/jobs/${jobId}/events/${event.id}.ics`).catch(
                    (error: Error) => toast.error(error.message),
                  );
                }}
              >
                <CalendarPlus aria-hidden="true" />
              </Button>
            )}
            <EventFormDialog
              trigger={
                <Button variant="ghost" size="icon-sm" aria-label={`Edit ${titleFor(event)}`}>
                  <Pencil aria-hidden="true" />
                </Button>
              }
              event={event}
              onSubmit={(body) => update.mutateAsync(body).then(() => undefined)}
            />
            <ConfirmDialog
              trigger={
                <Button variant="ghost" size="icon-sm" aria-label={`Delete ${titleFor(event)}`}>
                  <Trash2 aria-hidden="true" />
                </Button>
              }
              title="Delete this timeline event?"
              description="The application status will not move backward automatically."
              confirmLabel="Delete event"
              confirmDisabled={remove.isPending}
              onConfirm={() => remove.mutate()}
            />
          </div>
        </div>

        {meta.length > 0 && (
          <p className="mt-3 text-sm text-muted-foreground">{meta.join(" · ")}</p>
        )}
        {event.locationOrLink && (
          <p className="mt-2 flex min-w-0 items-center gap-2 text-sm">
            <MapPin className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            {isWebLink(event.locationOrLink) ? (
              <a
                href={event.locationOrLink}
                target="_blank"
                rel="noreferrer"
                className="truncate text-primary underline-offset-4 hover:underline"
              >
                {event.locationOrLink}
              </a>
            ) : (
              <span>{event.locationOrLink}</span>
            )}
          </p>
        )}
        {event.kind === "offer_received" && event.totalComp != null && (
          <p className="mt-3 font-heading text-lg font-semibold tabular-nums">
            {event.totalComp.toLocaleString()} {event.compCurrency ?? ""}
          </p>
        )}
        {(event.notes || event.reflection) && (
          <details className="group mt-3 rounded-lg bg-muted/35 px-3 py-2 text-sm">
            <summary className="cursor-pointer select-none font-medium">Notes & reflection</summary>
            <div className="mt-2 space-y-3 text-muted-foreground">
              {event.notes && <p className="whitespace-pre-wrap">{event.notes}</p>}
              {event.reflection && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.12em]">Reflection</p>
                  <p className="mt-1 whitespace-pre-wrap">{event.reflection}</p>
                </div>
              )}
            </div>
          </details>
        )}
      </article>
    </li>
  );
}
