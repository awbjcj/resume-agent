import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { UNASSIGNED_ID, type CategoryRow } from "../aggregate";
import type { NewDomainInput } from "../use-taxonomy";

type Category = { slug: string; label: string; kind: "hard" | "soft" };

export function DomainPicker({
  categoryRows,
  categories,
  domainId,
  newDomain,
  onDomainIdChange,
  onNewDomainChange,
}: {
  categoryRows: CategoryRow[];
  categories: Category[];
  domainId: string;
  newDomain: NewDomainInput | null;
  onDomainIdChange: (value: string) => void;
  onNewDomainChange: (value: NewDomainInput | null) => void;
}) {
  // The synthetic "Unassigned" domain is render-only and has no persisted id,
  // so it must never be offered as a move/add target.
  const pickableCategories = categoryRows
    .map((category) => ({
      ...category,
      domains: category.domains.filter((domain) => domain.id !== UNASSIGNED_ID),
    }))
    .filter((category) => category.domains.length > 0);
  const domainItems = pickableCategories.flatMap((category) =>
    category.domains.map((domain) => ({ label: domain.label, value: domain.id })),
  );
  const categoryItems = categories.map((category) => ({
    label: category.label,
    value: category.slug,
  }));
  return (
    <FieldGroup>
      {!newDomain && (
        <Field>
          <FieldLabel>Domain</FieldLabel>
          <Select
            items={domainItems}
            value={domainId || null}
            onValueChange={(value) => value && onDomainIdChange(value)}
          >
            <SelectTrigger className="w-full">
              <SelectValue>
                {domainId ? undefined : "Choose a domain"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              {pickableCategories.map((category) => (
                <SelectGroup key={category.slug}>
                  <SelectLabel>{category.label}</SelectLabel>
                  {category.domains.map((domain) => (
                    <SelectItem key={domain.id} value={domain.id}>
                      {domain.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </Field>
      )}
      {newDomain && (
        <>
          <Field>
            <FieldLabel htmlFor="new-domain-label">New domain label</FieldLabel>
            <Input
              id="new-domain-label"
              value={newDomain.label}
              onChange={(event) =>
                onNewDomainChange({ ...newDomain, label: event.target.value })
              }
            />
          </Field>
          <Field>
            <FieldLabel>Category</FieldLabel>
            <Select
              items={categoryItems}
              value={newDomain.category || null}
              onValueChange={(value) =>
                value && onNewDomainChange({ ...newDomain, category: value })
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue>
                  {newDomain.category ? undefined : "Choose a category"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {categories.map((category) => (
                    <SelectItem key={category.slug} value={category.slug}>
                      {category.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        </>
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() =>
          onNewDomainChange(newDomain ? null : { label: "", category: "" })
        }
      >
        {newDomain ? "Choose existing domain" : "New domain…"}
      </Button>
    </FieldGroup>
  );
}
