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

function compactText(value: string, maxLength: number): string {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  const firstSentence = text.match(/^.+?[.!?](?=\s|$)/)?.[0];
  if (firstSentence && firstSentence.length <= maxLength) return firstSentence;
  const clipped = text.slice(0, maxLength + 1);
  const wordBoundary = clipped.lastIndexOf(" ");
  return `${clipped.slice(0, wordBoundary > maxLength * 0.6 ? wordBoundary : maxLength).trimEnd()}…`;
}

function conciseQuestion(value: string): string {
  const text = value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^\s*(?:[>#-]\s*)+/gm, "")
    .replace(/[*_`~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const questions = text.match(/(?:^|[.!]\s+)([^.!?]*\?)/g);
  const lastQuestion = questions?.at(-1)?.replace(/^[.!]\s*/, "").trim();
  const lastSentence = text.match(/[^.!?]+[.!?]?/g)?.at(-1)?.trim();
  return compactText(lastQuestion || lastSentence || text, 140);
}

function statusFor(topic: Topic): { label: string; fulfilled: boolean } {
  if (topic.status === "skipped") return { label: "Skipped", fulfilled: false };
  if (topic.status !== "open") return { label: "Fulfilled", fulfilled: true };
  return { label: "Upcoming", fulfilled: false };
}

export function AgendaRail({ topics, currentTopicId, currentQuestion }: AgendaRailProps) {
  const titleId = useId();
  const currentTitleId = useId();
  const currentTopic = topics.find(
    (topic) => topic.id === currentTopicId && topic.status === "open",
  );
  const queuedTopics = currentTopic
    ? topics.filter((topic) => topic.id !== currentTopic.id)
    : topics;
  const openCount = topics.filter((topic) => topic.status === "open").length;
  const fulfilledCount = topics.filter(
    (topic) => topic.status !== "open" && topic.status !== "skipped",
  ).length;

  return (
    <Card className="overflow-hidden rounded-2xl bg-card/95 shadow-card">
      <CardHeader className="gap-2 border-b bg-muted/15 py-4">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>
            <h2 id={titleId} className="flex items-center gap-2 text-base">
              <FileCheck2 className="size-4 text-primary" aria-hidden="true" />
              Evidence path
            </h2>
          </CardTitle>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {openCount} open · {fulfilledCount} fulfilled
          </span>
        </div>
        <CardDescription className="text-xs leading-5">
          Current focus and the rest of the agenda.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <div
          aria-labelledby={titleId}
          className="max-h-[min(60svh,42rem)] overflow-y-auto overscroll-contain p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:p-5"
          role="region"
          tabIndex={0}
        >
          {currentTopic ? (
            <section
              aria-current="step"
              aria-labelledby={currentTitleId}
              className="rounded-xl border border-primary/20 bg-primary/[0.045] p-4"
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-[11px] font-semibold tracking-[0.12em] text-primary uppercase">
                  Current focus
                </span>
                <Badge variant="secondary">In progress</Badge>
              </div>
              <h3 id={currentTitleId} className="break-words text-sm leading-6 font-semibold text-foreground">
                {conciseQuestion(currentQuestion || currentTopic.gap)}
              </h3>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Goal · {compactText(currentTopic.gap, 96)}
              </p>
            </section>
          ) : null}

          {queuedTopics.length ? (
            <section className={cn(currentTopic && "mt-5")} aria-label="Evidence agenda">
              <div className="mb-1 flex items-center justify-between gap-3 px-1">
                <h3 className="text-xs font-semibold text-foreground">Agenda</h3>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {queuedTopics.length} item{queuedTopics.length === 1 ? "" : "s"}
                </span>
              </div>
              <ol className="divide-y">
                {queuedTopics.map((topic) => {
                  const saved = Boolean(topic.noteDocId);
                  const status = statusFor(topic);
                  return (
                    <li className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] gap-2.5 py-3" key={topic.id}>
                      <span
                        className={cn(
                          "mt-0.5 flex size-5 items-center justify-center rounded-full border",
                          status.fulfilled && "bg-muted text-muted-foreground",
                          !status.fulfilled && topic.status !== "skipped" && "bg-background text-muted-foreground",
                          topic.status === "skipped" && "border-dashed text-muted-foreground/70",
                        )}
                      >
                        {saved ? (
                          <FileCheck2 className="size-3 text-primary" aria-hidden="true" />
                        ) : status.fulfilled ? (
                          <Check className="size-3" aria-hidden="true" />
                        ) : (
                          <Circle className="size-2 fill-current" aria-hidden="true" />
                        )}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm leading-5 font-medium">
                          {compactText(topic.gap, 80)}
                        </p>
                        {topic.status === "open" && topic.whyItMatters ? (
                          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                            {compactText(topic.whyItMatters, 100)}
                          </p>
                        ) : null}
                      </div>
                      <Badge
                        className="mt-0.5"
                        variant={status.fulfilled ? "secondary" : "outline"}
                      >
                        {status.label}
                      </Badge>
                    </li>
                  );
                })}
              </ol>
            </section>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
