import type { components } from "@/lib/api/schema";
import { useTranslation } from "react-i18next";

import { applicationStatusLabel } from "@/features/applications/application-labels";
import { stageLabel } from "./chart-theme";

type PipelineLane = components["schemas"]["PipelineLaneOut"];

export function toLanes(pipeline: PipelineLane[], now: Date = new Date()) {
  const rows = pipeline
    .map((lane) => ({
      ...lane,
      events: lane.events
        .map((event) => ({ ...event, date: new Date(event.occurredAt) }))
        .filter((event) => Number.isFinite(event.date.getTime())),
    }))
    .filter((lane) => lane.events.length > 0);
  const allTimes = rows.flatMap((lane) => lane.events.map((event) => event.date.getTime()));
  const min = Math.min(now.getTime(), ...allTimes);
  const max = Math.max(now.getTime(), ...allTimes);
  const span = max - min;
  return rows
    .map((lane) => {
      const events = lane.events.map((event) => ({
        ...event,
        upcoming: event.date.getTime() >= now.getTime(),
        position: span === 0 ? 50 : ((event.date.getTime() - min) / span) * 100,
      }));
      const upcoming = events.filter((event) => event.upcoming).map((event) => event.date.getTime());
      const sortTime = upcoming.length ? Math.min(...upcoming) : -Math.max(...events.map((event) => event.date.getTime()));
      return { ...lane, events, sortTime, todayPosition: span === 0 ? 50 : ((now.getTime() - min) / span) * 100 };
    })
    .sort((left, right) => left.sortTime - right.sortTime);
}

export function PipelineTimelineChart({ pipeline, now }: { pipeline: PipelineLane[]; now?: Date }) {
  const { t } = useTranslation();
  const lanes = toLanes(pipeline, now);
  if (lanes.length === 0) {
    return <p className="text-sm text-muted-foreground">No active applications with dated events yet.</p>;
  }
  return (
    <div className="min-w-0 overflow-x-auto">
      <div className="min-w-[42rem] space-y-2">
        <div className="grid grid-cols-[11rem_minmax(28rem,1fr)] gap-3 text-xs font-medium text-muted-foreground">
          <span>Application</span><span>Timeline · today is the vertical line</span>
        </div>
        {lanes.map((lane) => (
          <div key={lane.jobId} className="grid grid-cols-[11rem_minmax(28rem,1fr)] items-center gap-3 rounded-md px-2 py-2 hover:bg-muted/30">
            <div className="min-w-0"><p className="truncate font-medium">{lane.company || t("applicationTimeline.applicationFallback")}</p><p className="truncate text-xs text-muted-foreground">{lane.title || applicationStatusLabel(t, lane.status)}</p></div>
            <div className="relative h-9 rounded bg-muted/40">
              <span className="absolute inset-y-0 w-px bg-foreground/45" style={{ left: `${lane.todayPosition}%` }} aria-hidden="true" />
              {lane.events.map((event, index) => (
                <span
                  key={`${event.kind}-${event.sequence}-${index}`}
                  title={`${stageLabel(event.kind, t)} · ${event.date.toLocaleDateString()}`}
                  aria-label={`${stageLabel(event.kind, t)}, ${event.date.toLocaleDateString()}`}
                  className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-background ${event.upcoming ? "bg-primary" : "bg-muted-foreground"}`}
                  style={{ left: `${event.position}%` }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
