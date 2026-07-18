import { ClipboardCheck } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import type { InterviewDebrief, InterviewSession } from "./use-interview";

type PlanItem = NonNullable<InterviewSession["plan"]>[number];

function Bullets({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">{title}</p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function DebriefCard({
  debrief,
  plan,
}: {
  debrief: InterviewDebrief;
  plan: PlanItem[];
}) {
  return (
    <Card>
      <CardHeader className="border-b bg-muted/20">
        <CardTitle className="flex items-center gap-2 text-lg">
          <ClipboardCheck className="size-5 text-primary" aria-hidden="true" />
          Interview debrief
        </CardTitle>
        <CardDescription className="text-base leading-7 text-foreground">
          {debrief.summary}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6 pt-6">
        {debrief.questionReviews?.length ? (
          <Accordion className="w-full">
            {debrief.questionReviews.map((review) => (
              <AccordionItem key={review.questionId} value={review.questionId}>
                <AccordionTrigger className="text-left">
                  <span className="flex flex-1 items-center justify-between gap-3 pr-2">
                    <span className="text-sm font-medium">{review.question || review.questionId}</span>
                    <Badge variant="secondary">{review.score}/5</Badge>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="space-y-3">
                  <Bullets title="Strengths" items={review.strengths ?? []} />
                  <Bullets title="Improvements" items={review.improvements ?? []} />
                  {review.suggestedAnswer ? (
                    <div className="space-y-1">
                      <p className="text-sm font-medium">A stronger answer</p>
                      <p className="rounded-lg bg-muted/50 p-3 text-sm leading-6">{review.suggestedAnswer}</p>
                    </div>
                  ) : null}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Bullets title="What went well" items={debrief.strengths ?? []} />
          <Bullets title="Where to sharpen" items={debrief.improvements ?? []} />
        </div>

        {debrief.starNotes ? (
          <div className="space-y-1">
            <p className="text-sm font-medium">STAR notes</p>
            <p className="text-sm leading-6 text-muted-foreground">{debrief.starNotes}</p>
          </div>
        ) : null}

        {plan.length ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">Questions planned</p>
            <ul className="space-y-1 text-sm text-muted-foreground">
              {plan.map((item) => (
                <li key={item.id}>
                  {item.competency}
                  {item.questionType ? <span className="text-xs"> · {item.questionType}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
