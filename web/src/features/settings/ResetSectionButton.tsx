import { useState } from "react";
import { RotateCcw } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

import { useResetSection } from "./use-settings-sections";

/** Restores one settings section to the value a fresh workspace would have.
 *  Used both in the Backup page's section table and on individual settings
 *  pages, so the confirm copy stays identical wherever a reset is offered.
 *  `buttonLabel` overrides the face text for pages that show more than one
 *  reset side-by-side (Rendering), where the generic "Reset to defaults" would
 *  be ambiguous; the confirm dialog always names the section via `label`. */
export function ResetSectionButton({
  sectionId,
  label,
  note,
  buttonLabel = "Reset to defaults",
}: {
  sectionId: string;
  label: string;
  note?: string;
  buttonLabel?: string;
}) {
  const reset = useResetSection();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={<Button variant="outline" size="sm" />}>
        <RotateCcw data-icon="inline-start" />
        {buttonLabel}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia>
            <RotateCcw aria-hidden="true" />
          </AlertDialogMedia>
          <AlertDialogTitle>Reset {label} to defaults?</AlertDialogTitle>
          <AlertDialogDescription>
            This replaces your {label.toLowerCase()} with the shipped default.
            Your current values are lost — export a settings bundle first if you
            want them back.
            {note ? ` ${note}` : ""}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={reset.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={reset.isPending}
            onClick={(event) => {
              event.preventDefault();
              reset.mutate(
                { sectionId },
                { onSuccess: () => setOpen(false) },
              );
            }}
          >
            {reset.isPending ? <Spinner data-icon="inline-start" /> : null}
            Reset
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
