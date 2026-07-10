import { CircleAlert, Layers3 } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";

import type { ProfileMatrix } from "./use-matrix";
import { useMatrix } from "./use-matrix";

type MatrixRow = NonNullable<ProfileMatrix["rows"]>[number];

export function SkillGroupsPanel() {
  const matrix = useMatrix();

  if (matrix.isPending) {
    return <Skeleton className="h-48 w-full" aria-label="Loading skill matrix" />;
  }
  if (matrix.isError) {
    return (
      <Alert variant="destructive">
        <CircleAlert aria-hidden="true" />
        <AlertTitle>Couldn't load the skill matrix</AlertTitle>
        <AlertDescription>{matrix.error.message}</AlertDescription>
        <AlertAction>
          <Button size="sm" variant="outline" onClick={() => matrix.refetch()}>
            Try again
          </Button>
        </AlertAction>
      </Alert>
    );
  }

  const rows = matrix.data.rows ?? [];
  if (rows.length === 0) {
    return (
      <section aria-labelledby="skill-groups-heading">
        <h2 id="skill-groups-heading" className="mb-3 text-base font-semibold">Skill groups</h2>
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon"><Layers3 aria-hidden="true" /></EmptyMedia>
            <EmptyTitle>No grouped skills yet</EmptyTitle>
            <EmptyDescription>Run a profile build to classify your skill matrix.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      </section>
    );
  }

  const groups = matrix.data.groups ?? [];
  const known = new Set(groups.map((group) => group.slug));
  const byGroup = new Map<string, MatrixRow[]>();
  for (const group of groups) byGroup.set(group.slug, []);
  if (!byGroup.has("other")) byGroup.set("other", []);
  for (const row of rows) {
    const slug = row.group && known.has(row.group) ? row.group : "other";
    byGroup.get(slug)?.push(row);
  }
  const orderedGroups = [
    ...groups.filter((group) => group.slug !== "other"),
    groups.find((group) => group.slug === "other") ?? { slug: "other", label: "Other" },
  ];

  return (
    <section aria-labelledby="skill-groups-heading">
      <h2 id="skill-groups-heading" className="text-base font-semibold">Skill groups</h2>
      <p className="mb-2 text-sm text-muted-foreground">
        Profile skills grouped by their primary professional use.
      </p>
      <Accordion multiple defaultValue={orderedGroups.map((group) => group.slug)}>
        {orderedGroups.map((group) => {
          const members = byGroup.get(group.slug) ?? [];
          return (
            <AccordionItem key={group.slug} value={group.slug}>
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  {group.label}
                  <Badge variant="secondary">{members.length}</Badge>
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <div className="flex flex-wrap gap-2">
                  {members.length > 0 ? members.map((row) => (
                    <Badge key={row.key} variant="outline">{row.display}</Badge>
                  )) : (
                    <span className="text-xs text-muted-foreground">No skills in this group.</span>
                  )}
                </div>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    </section>
  );
}
