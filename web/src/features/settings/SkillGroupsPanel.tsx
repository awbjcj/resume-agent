import { Check, CircleAlert, Pin, Trash2, Undo2 } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

import { AddSkillToGroupPopover } from "./AddSkillToGroupPopover";
import type { ProfileMatrix } from "./use-matrix";
import {
  useClearSkillGroup,
  useDeleteSkill,
  useMatrix,
  useRestoreSkill,
  useSetSkillGroup,
  useSuppressedSkills,
} from "./use-matrix";

type MatrixRow = NonNullable<ProfileMatrix["rows"]>[number];

export function SkillGroupsPanel() {
  const matrix = useMatrix();
  const setGroup = useSetSkillGroup();
  const clearGroup = useClearSkillGroup();
  const deleteSkill = useDeleteSkill();
  const restoreSkill = useRestoreSkill();
  const suppressed = useSuppressedSkills();

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
  const populatedGroups = orderedGroups
    .filter((group) => (byGroup.get(group.slug)?.length ?? 0) > 0)
    .map((group) => group.slug);

  return (
    <section aria-labelledby="skill-groups-heading">
      <h2 id="skill-groups-heading" className="text-base font-semibold">Skill groups</h2>
      <p className="mb-2 text-sm text-muted-foreground">
        Profile skills grouped by their primary professional use. Click a skill to move it;
        open any category to add a new one. Corrections are pinned and survive profile rebuilds.
      </p>
      <Accordion multiple defaultValue={populatedGroups}>
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
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span className="text-xs text-muted-foreground">
                    {members.length === 0
                      ? "No skills in this category yet."
                      : `${members.length} skill${members.length === 1 ? "" : "s"}`}
                  </span>
                  <AddSkillToGroupPopover group={group} />
                </div>
                {members.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {members.map((row) => {
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
                        <DropdownMenuContent
                          align="start"
                          className="max-h-80 w-72 min-w-72"
                        >
                          <DropdownMenuGroup>
                            <DropdownMenuLabel>Move to…</DropdownMenuLabel>
                            {orderedGroups.map((target) => (
                              <DropdownMenuItem
                                key={target.slug}
                                className="whitespace-nowrap"
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
                          <DropdownMenuSeparator />
                          <DropdownMenuGroup>
                            <DropdownMenuItem
                              variant="destructive"
                              disabled={deleteSkill.isPending}
                              onClick={() => deleteSkill.mutate(row.key)}
                            >
                              <Trash2 aria-hidden />
                              Delete skill
                            </DropdownMenuItem>
                          </DropdownMenuGroup>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    );
                    })}
                  </div>
                ) : null}
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
      {suppressed.data && suppressed.data.length > 0 ? (
        <section aria-labelledby="suppressed-heading" className="mt-6">
          <h3 id="suppressed-heading" className="text-sm font-semibold">
            Deleted skills
          </h3>
          <p className="mb-2 text-sm text-muted-foreground">
            These stay removed across profile rebuilds until you restore them.
          </p>
          <ul className="flex flex-wrap gap-2">
            {suppressed.data.map((skill) => (
              <li key={skill.token}>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={restoreSkill.isPending}
                  aria-label={`Restore ${skill.display}`}
                  onClick={() => restoreSkill.mutate(skill.token)}
                >
                  <Undo2 aria-hidden data-icon="inline-start" />
                  {skill.display}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
