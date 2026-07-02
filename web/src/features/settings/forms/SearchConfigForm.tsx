import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from "@/components/ui/accordion";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { paths } from "@/lib/api/schema";

import { TagListInput } from "./TagListInput";

export type SearchDoc =
  paths["/api/config/search"]["get"]["responses"][200]["content"]["application/json"];

const REMOTE_OPTIONS = [
  { value: "remote_only", label: "Remote only" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];

function numOrNull(raw: string): number | null {
  return raw === "" ? null : Number(raw);
}

export function SearchConfigForm({
  value, onChange,
}: {
  value: SearchDoc; onChange: (next: SearchDoc) => void;
}) {
  const set = <K extends keyof SearchDoc>(key: K, v: SearchDoc[K]) =>
    onChange({ ...value, [key]: v });

  const remotePolicySelection = value.remotePolicy ? [value.remotePolicy] : [];

  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="keywords">Keywords</FieldLabel>
        <TagListInput id="keywords" value={value.keywords ?? []}
          onChange={(v) => set("keywords", v)} placeholder="python, distributed systems…" />
      </Field>
      <Field>
        <FieldLabel htmlFor="titles">Titles</FieldLabel>
        <TagListInput id="titles" value={value.titles ?? []}
          onChange={(v) => set("titles", v)} placeholder="Software Engineer…" />
      </Field>
      <Field>
        <FieldLabel htmlFor="locations">Locations</FieldLabel>
        <TagListInput id="locations" value={value.locations ?? []}
          onChange={(v) => set("locations", v)} placeholder="Remote, Austin TX…" />
      </Field>
      <Field>
        <FieldLabel>Remote policy</FieldLabel>
        <ToggleGroup
          value={remotePolicySelection}
          onValueChange={(next) => {
            const added = next.find((v) => !remotePolicySelection.includes(v));
            set("remotePolicy", added ?? null);
          }}
        >
          {REMOTE_OPTIONS.map((o) => (
            <ToggleGroupItem key={o.value} value={o.value}>{o.label}</ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field>
          <FieldLabel htmlFor="minSalary">Minimum salary</FieldLabel>
          <Input id="minSalary" type="number" value={value.minSalary ?? ""}
            onChange={(e) => set("minSalary", numOrNull(e.target.value))} />
        </Field>
        <Field>
          <FieldLabel htmlFor="yoeMin">Years of experience, min</FieldLabel>
          <Input id="yoeMin" type="number" value={value.yoeMin ?? ""}
            onChange={(e) => set("yoeMin", numOrNull(e.target.value))} />
        </Field>
        <Field>
          <FieldLabel htmlFor="yoeMax">Years of experience, max</FieldLabel>
          <Input id="yoeMax" type="number" value={value.yoeMax ?? ""}
            onChange={(e) => set("yoeMax", numOrNull(e.target.value))} />
        </Field>
      </div>
      <Field>
        <div className="flex items-center gap-3">
          <Switch id="sponsorship" checked={value.sponsorshipRequired ?? false}
            onCheckedChange={(v: boolean) => set("sponsorshipRequired", v)} />
          <FieldLabel htmlFor="sponsorship">I need visa sponsorship</FieldLabel>
        </div>
      </Field>
      <Accordion>
        <AccordionItem value="tuning">
          <AccordionTrigger>Relevance tuning</AccordionTrigger>
          <AccordionContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="roleAnchors">Role anchors</FieldLabel>
                <TagListInput id="roleAnchors" value={value.roleAnchors ?? []}
                  onChange={(v) => set("roleAnchors", v)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="excludeTerms">Exclude terms</FieldLabel>
                <TagListInput id="excludeTerms" value={value.excludeTerms ?? []}
                  onChange={(v) => set("excludeTerms", v)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="targetRole">Target role</FieldLabel>
                <Input id="targetRole" value={value.targetRole ?? ""}
                  onChange={(e) => set("targetRole", e.target.value || null)} />
              </Field>
            </FieldGroup>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </FieldGroup>
  );
}
