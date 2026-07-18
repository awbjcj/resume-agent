import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePatchDomain } from "../use-taxonomy";
type Category = { slug: string; label: string; kind: "hard" | "soft" };
export function ChangeCategoryDialog({
  domainId,
  currentSlug,
  categories,
  open,
  onOpenChange,
}: {
  domainId: string;
  currentSlug: string;
  categories: Category[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [category, setCategory] = useState(currentSlug);
  const mutation = usePatchDomain();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change category</DialogTitle>
          <DialogDescription>
            Move this domain beneath another category.
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel>Category</FieldLabel>
          <Select
            items={categories.map((item) => ({ label: item.label, value: item.slug }))}
            value={category}
            onValueChange={(value) => value && setCategory(value)}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {categories.map((item) => (
                  <SelectItem key={item.slug} value={item.slug}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { domainId, body: { category } },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
