import { useId } from "react";
import { Check, Circle, FileCheck2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

type Topic = components["schemas"]["CoachTopicOut"];

type AgendaRailProps = {
  topics: Topic[];
  currentTopicId?: string;
  currentQuestion?: string;
};

export function AgendaRail({ topics, currentTopicId, currentQuestion }: AgendaRailProps) {
  const titleId = useId();
  const currentTopic = topics.find(
    (topic) => topic.id === currentTopicId && topic.status === "open",
  );
  const orderedTopics = currentTopic
    ? [currentTopic, ...topics.filter((topic) => topic.id !== currentTopic.id)]
    : topics;

  return (
    <Card className="rounded-2xl bg-card/95 shadow-card">
      <CardHeader>
        <CardTitle>
          <h2 id={titleId} className="flex items-center gap-2 text-base">
            <FileCheck2 className="size-4 text-primary" aria-hidden="true" />
            Evidence path
          </h2>
        </CardTitle>
        <CardDescription className="text-sm leading-relaxed">One focused gap at a time, grounded in your own evidence.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <div
          aria-labelledby={titleId}
          className="max-h-[min(60svh,42rem)] overflow-y-auto overscroll-contain px-6 pb-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          role="region"
          tabIndex={0}
        >
          <ol className="relative">
            {orderedTopics.map((topic, index) => {
              const done = topic.status !== "open";
              const saved = Boolean(topic.noteDocId);
              const current = topic.id === currentTopic?.id;
              const fulfilled = done && topic.status !== "skipped";
              let statusLabel = "Upcoming";
              if (current) statusLabel = "In progress";
              else if (fulfilled) statusLabel = "Fulfilled";
              else if (topic.status === "skipped") statusLabel = "Skipped";

              return (
                <li
                  className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0"
                  key={topic.id}
                  aria-current={current ? "step" : undefined}
                >
                  {index < orderedTopics.length - 1 ? (
                    <span className="absolute top-6 bottom-0 left-[0.7rem] w-px bg-border" aria-hidden="true" />
                  ) : null}
                  <span
                    className={cn(
                      "relative z-10 flex size-6 items-center justify-center rounded-full border",
                      done && "bg-muted text-muted-foreground",
                      current && "border-primary/35 bg-primary/10 text-primary",
                      !done && !current && "bg-background text-muted-foreground",
                    )}
                  >
                    {saved ? (
                      <FileCheck2 className="size-3.5 text-primary" aria-hidden="true" />
                    ) : done ? (
                      <Check className="size-3.5" aria-hidden="true" />
                    ) : (
                      <Circle className="size-2.5 fill-current" aria-hidden="true" />
                    )}
                  </span>
                  <div className="min-w-0 space-y-1">
                    <div className="text-sm font-semibold leading-snug">
                      {current && currentQuestion ? currentQuestion : topic.gap}
                    </div>
                    {current && currentQuestion ? (
                      <p className="text-xs font-medium text-muted-foreground">Evidence gap: {topic.gap}</p>
                    ) : null}
                    <p className="text-sm leading-relaxed text-muted-foreground">{topic.whyItMatters}</p>
                    <Badge variant={current || fulfilled ? "secondary" : "outline"} className="mt-1">
                      {statusLabel}
                    </Badge>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </CardContent>
    </Card>
  );
}
