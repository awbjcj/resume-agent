import { CalendarPlus, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EventFormDialog } from "./EventFormDialog";
import { EventRow } from "./EventRow";
import { useApplicationEvents, useCreateEvent } from "./use-application-events";

export function ApplicationTimeline({ jobId }: { jobId: number }) {
  const { data: events = [], isPending } = useApplicationEvents(jobId);
  const create = useCreateEvent(jobId);
  const add = (
    <EventFormDialog
      trigger={
        <Button size="sm">
          <CalendarPlus aria-hidden="true" />
          Add event
        </Button>
      }
      onSubmit={(body) => create.mutateAsync(body).then(() => undefined)}
    />
  );

  if (isPending) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        Loading timeline…
      </div>
    );
  }

  return (
    <section aria-labelledby="application-timeline-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h4 id="application-timeline-heading" className="font-heading text-base font-semibold">
            Timeline
          </h4>
          <p className="text-sm text-muted-foreground">
            Every touchpoint, decision, and upcoming date in one place.
          </p>
        </div>
        {add}
      </div>

      {events.length === 0 ? (
        <div className="rounded-xl border border-dashed bg-muted/20 px-4 py-8 text-center">
          <p className="font-medium">No events yet.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add the application date or your next interview to start the record.
          </p>
        </div>
      ) : (
        <ol className="relative space-y-3 before:absolute before:bottom-6 before:left-2 before:top-3 before:w-px before:bg-border">
          {events.map((event) => (
            <EventRow key={event.id} event={event} jobId={jobId} />
          ))}
        </ol>
      )}
    </section>
  );
}
