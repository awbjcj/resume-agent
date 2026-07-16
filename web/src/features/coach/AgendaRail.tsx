import { Check, Circle, FileCheck2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";

type Topic = components["schemas"]["CoachTopicOut"];

export function AgendaRail({ topics }: { topics: Topic[] }) {
  return (
    <Card className="bg-muted/20 shadow-none">
      <CardHeader>
        <CardTitle className="text-base">Coaching agenda</CardTitle>
        <CardDescription className="text-sm leading-relaxed">Evidence gaps selected from your current profile.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {topics.map((topic) => {
          const done = topic.status !== "open";
          return (
            <div className="flex gap-4" key={topic.id}>
              <div className="mt-0.5 text-muted-foreground">
                {topic.noteDocId ? <FileCheck2 className="size-4 text-primary" aria-hidden="true" /> : done ? <Check className="size-4" aria-hidden="true" /> : <Circle className="size-4" aria-hidden="true" />}
              </div>
              <div className="min-w-0 space-y-1">
                <div className="text-base font-medium leading-snug">{topic.gap}</div>
                <p className="text-sm leading-relaxed text-muted-foreground">{topic.whyItMatters}</p>
                <Badge variant="outline" className="mt-1">{topic.status}</Badge>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
