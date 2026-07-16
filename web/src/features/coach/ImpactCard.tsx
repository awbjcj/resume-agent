import { ArrowUpRight, ChartNoAxesColumnIncreasing, Sparkles } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";

type Impact = components["schemas"]["CoachImpactOut"];

export function ImpactCard({ impact }: { impact: Impact }) {
  if (impact.error) {
    return <Alert variant="destructive"><AlertTitle>Impact comparison unavailable</AlertTitle><AlertDescription>{impact.error}</AlertDescription></Alert>;
  }
  return (
    <Card className="border-primary/25 bg-gradient-to-br from-card via-card to-primary/[0.06]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" aria-hidden="true" />Coaching impact</CardTitle>
        <CardDescription>What changed in the rebuilt profile.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <div><div className="text-2xl font-semibold tabular-nums">{(impact.newFactIds ?? []).length}</div><div className="text-xs text-muted-foreground">new grounded facts</div></div>
        <div><div className="text-2xl font-semibold tabular-nums">{(impact.bulletsGainedMetrics ?? []).length}</div><div className="text-xs text-muted-foreground">bullets gained metrics</div></div>
        <div><div className="text-2xl font-semibold tabular-nums">{(impact.skillsGainedEvidence ?? []).length}</div><div className="text-xs text-muted-foreground">skills gained evidence</div></div>
        {(impact.newSkills ?? []).length ? <div className="sm:col-span-3 flex flex-wrap gap-2">{impact.newSkills?.map((skill) => <Badge key={skill} variant="secondary"><ArrowUpRight aria-hidden="true" />{skill}</Badge>)}</div> : null}
        {((impact.bulletsGainedMetrics ?? []).length || (impact.skillsGainedEvidence ?? []).length) ? <div className="sm:col-span-3 flex items-center gap-2 text-xs text-muted-foreground"><ChartNoAxesColumnIncreasing className="size-4" aria-hidden="true" />Counts compare the profile immediately before and after this session.</div> : null}
      </CardContent>
    </Card>
  );
}
