import { useId, useState } from "react";
import { ExternalLink, RotateCw, ShieldAlert } from "lucide-react";

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { canManuallyConfirm, verificationLabel } from "./proposals";
import type { ScoutProposal } from "./use-scout";

type Props = {
  proposal: ScoutProposal;
  scrapeAvailable: boolean;
  resolvePending?: boolean;
  confirmPending?: boolean;
  onResolve: (url: string) => Promise<unknown>;
  onConfirm: () => Promise<unknown>;
};

function isPublicHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function readableReason(reason: string): string {
  return reason ? reason.replaceAll("_", " ").toLowerCase() : "ownership is not proven";
}

/** Compact recovery and override controls for a non-verified Scout source. */
export function SourceVerificationActions({
  proposal,
  scrapeAvailable,
  resolvePending = false,
  confirmPending = false,
  onResolve,
  onConfirm,
}: Props) {
  const source = proposal.source;
  const inputId = useId();
  const affirmationId = useId();
  const initialUrl = source?.canonicalBoardUrl || source?.requestedUrl || source?.url || "";
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState(initialUrl);
  const [affirmed, setAffirmed] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState("");
  const label = verificationLabel(proposal);
  const retryAvailable = proposal.status === "pending"
    && proposal.kind === "source"
    && ["unverified", "conflict", "failed"].includes(proposal.check);
  const manualAvailable = canManuallyConfirm(proposal, scrapeAvailable);

  if (!source || (!retryAvailable && !manualAvailable)) return null;

  const resetConfirmation = () => {
    setAffirmed(false);
    setError("");
  };

  const submitResolution = async () => {
    const candidate = url.trim();
    if (!isPublicHttpUrl(candidate)) {
      setError("Enter a complete HTTP(S) URL.");
      return;
    }
    setError("");
    try {
      await onResolve(candidate);
      setEditing(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The board could not be resolved.");
    }
  };

  const submitConfirmation = async () => {
    setError("");
    try {
      await onConfirm();
      setConfirmOpen(false);
      resetConfirmation();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The board could not be added.");
    }
  };

  return (
    <div className="space-y-2 border-t border-border/60 pt-2">
      {label ? <p className="font-medium text-foreground">{label}</p> : null}
      <p className="text-muted-foreground">Resolution: {readableReason(source.resolutionReason)}</p>
      <div className="flex flex-wrap items-center gap-2">
        {isPublicHttpUrl(initialUrl) ? (
          <a
            href={initialUrl}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline", size: "xs" }))}
          >
            Open board <ExternalLink aria-hidden="true" />
          </a>
        ) : null}
        {retryAvailable ? (
          <Button
            size="xs"
            variant="outline"
            aria-expanded={editing}
            onClick={() => {
              if (editing) {
                setEditing(false);
              } else {
                setUrl(initialUrl);
                setEditing(true);
              }
              setError("");
            }}
          >
            Try another URL <RotateCw aria-hidden="true" />
          </Button>
        ) : null}
        {manualAvailable ? (
          <AlertDialog
            open={confirmOpen}
            onOpenChange={(open) => {
              setConfirmOpen(open);
              if (!open) resetConfirmation();
            }}
          >
            <AlertDialogTrigger render={<Button size="xs" variant="destructive" />}>
              Confirm and add anyway <ShieldAlert aria-hidden="true" />
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Confirm unverified board</AlertDialogTitle>
                <AlertDialogDescription>
                  This bypass is recorded with the exact board URL. Review the source before adding it.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <dl className="grid gap-1.5 rounded-lg border bg-muted/30 p-3 text-sm">
                <div className="grid grid-cols-[auto_1fr] gap-x-2"><dt className="text-muted-foreground">Company</dt><dd className="truncate font-medium">{source.company}</dd></div>
                <div className="grid grid-cols-[auto_1fr] gap-x-2"><dt className="text-muted-foreground">Board</dt><dd className="truncate font-medium">{initialUrl || "Unknown"}</dd></div>
                <div className="grid grid-cols-[auto_1fr] gap-x-2"><dt className="text-muted-foreground">ATS</dt><dd>{source.ats ?? "Unknown"}</dd></div>
                <div className="grid grid-cols-[auto_1fr] gap-x-2"><dt className="text-muted-foreground">Reason</dt><dd>{readableReason(source.resolutionReason)}</dd></div>
              </dl>
              <label className="flex cursor-pointer items-start gap-2 text-sm" htmlFor={affirmationId}>
                <Checkbox id={affirmationId} checked={affirmed} onCheckedChange={(checked) => setAffirmed(checked === true)} />
                <span>I manually confirmed this is {source.company}'s official job board.</span>
              </label>
              <AlertDialogFooter>
                <Button variant="ghost" onClick={() => setConfirmOpen(false)}>Cancel</Button>
                <Button variant="destructive" disabled={!affirmed || confirmPending} onClick={() => { void submitConfirmation(); }}>
                  Confirm and add
                </Button>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : null}
      </div>
      {editing ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            void submitResolution();
          }}
        >
          <label className="block font-medium" htmlFor={inputId}>Board URL for {source.company}</label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input id={inputId} value={url} onChange={(event) => setUrl(event.target.value)} inputMode="url" autoComplete="url" />
            <Button size="sm" type="submit" disabled={resolvePending}>Resolve URL</Button>
          </div>
        </form>
      ) : null}
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    </div>
  );
}
