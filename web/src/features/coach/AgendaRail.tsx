import { Check, Circle, FileCheck2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";

type Topic = components["schemas"]["CoachTopicOut"];

export function AgendaRail({ topics }: { topics: Topic[] }) {
  return (
    <Card className="rounded-2xl bg-card/95 shadow-card">
      <CardHeader>
        <CardTitle><h2 className="flex items-center gap-2 text-base"><FileCheck2 className="size-4 text-primary" aria-hidden="true" />Evidence path</h2></CardTitle>
        <CardDescription className="text-sm leading-relaxed">One focused gap at a time, grounded in your own evidence.</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="relative">
        {topics.map((topic, index) => {
          const done = topic.status !== "open";
          const saved = Boolean(topic.noteDocId);
          return (
            <li
              className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0"
              key={topic.id}
              aria-current={!done ? "step" : undefined}
            >
              {index < topics.length - 1 ? <span className="absolute top-6 bottom-0 left-[0.7rem] w-px bg-border" aria-hidden="true" /> : null}
              <span className={done ? "relative z-10 flex size-6 items-center justify-center rounded-full border bg-muted text-muted-foreground" : "relative z-10 flex size-6 items-center justify-center rounded-full border border-primary/35 bg-primary/10 text-primary"}>
                {saved ? <FileCheck2 className="size-3.5 text-primary" aria-hidden="true" /> : done ? <Check className="size-3.5" aria-hidden="true" /> : <Circle className="size-2.5 fill-current" aria-hidden="true" />}
              </span>
              <div className="min-w-0 space-y-1">
                <div className="text-sm font-semibold leading-snug">{topic.gap}</div>
                <p className="text-sm leading-relaxed text-muted-foreground">{topic.whyItMatters}</p>
                <Badge variant={saved ? "secondary" : "outline"} className="mt-1 capitalize">{saved ? "Saved" : topic.status}</Badge>
              </div>
            </li>
          );
        })}
        </ol>
      </CardContent>
    </Card>
  );
}
