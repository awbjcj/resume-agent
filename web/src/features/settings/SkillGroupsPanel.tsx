import { Check, CircleAlert, Layers3, Pin, Undo2 } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";

import type { ProfileMatrix } from "./use-matrix";
import { useClearSkillGroup, useMatrix, useSetSkillGroup } from "./use-matrix";

type MatrixRow = NonNullable<ProfileMatrix["rows"]>[number];

export function SkillGroupsPanel() {
  const matrix = useMatrix();
  const setGroup = useSetSkillGroup();
  const clearGroup = useClearSkillGroup();

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
        Profile skills grouped by their primary professional use. Click a skill to move it;
        corrections are pinned and survive profile rebuilds.
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
                  {members.length > 0 ? members.map((row) => {
                    const current = row.group && known.has(row.group) ? row.group : "other";
                    return (
                      <DropdownMenu key={row.key}>
                        <DropdownMenuTrigger
                          render={(
                            <Badge
                              render={<button type="button" />}
                              variant="outline"
                            />
                          )}
                          aria-label={`Change group for ${row.display}`}
                          disabled={setGroup.isPending || clearGroup.isPending}
                        >
                          {row.groupSource === "correction" ? (
                            <Pin aria-hidden data-icon="inline-start" />
                          ) : null}
                          {row.display}
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuGroup>
                            <DropdownMenuLabel>Move to…</DropdownMenuLabel>
                            {orderedGroups.map((target) => (
                              <DropdownMenuItem
                                key={target.slug}
                                disabled={setGroup.isPending || target.slug === current}
                                onClick={() =>
                                  setGroup.mutate({ key: row.key, group: target.slug })
                                }
                              >
                                {target.label}
                                {target.slug === current ? <Check aria-hidden /> : null}
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuGroup>
                          {row.groupSource === "correction" ? (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuGroup>
                                <DropdownMenuItem
                                  disabled={clearGroup.isPending}
                                  onClick={() => clearGroup.mutate(row.key)}
                                >
                                  <Undo2 aria-hidden />
                                  Reset to automatic
                                </DropdownMenuItem>
                              </DropdownMenuGroup>
                            </>
                          ) : null}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    );
                  }) : (
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
