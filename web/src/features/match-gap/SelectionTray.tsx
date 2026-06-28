import { useState } from "react";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  Clock3Icon,
  FlaskConicalIcon,
  RefreshCwIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { targetId, type SuggestionState, type SuggestionTarget } from "./aggregate";

const STATUS_LABEL: Record<SuggestionState, string> = {
  none: "Not generated",
  ready: "Ready",
  stale: "Stale",
  queued: "Queued",
  researching: "Researching",
  failed: "Failed",
  cancelled: "Cancelled",
  not_found: "Unavailable",
};

function Status({ state }: { state: SuggestionState }) {
  const Icon =
    state === "ready"
      ? CheckCircle2Icon
      : state === "failed" || state === "cancelled" || state === "not_found"
        ? AlertCircleIcon
        : Clock3Icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs text-muted-foreground",
        state === "ready" && "text-ready",
        (state === "failed" || state === "not_found") && "text-destructive",
      )}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {STATUS_LABEL[state]}
    </span>
  );
}

function TrayContents({
  targets,
  stateOf,
  onRemove,
  onClear,
  onGenerateAll,
  onRetry,
  generating,
  launchError,
}: SelectionTrayProps) {
  const launchableTargets = targets.filter((target) => {
    const state = stateOf(target.kind, target.key);
    return state !== "queued" && state !== "researching";
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
        <span className="font-mono text-xs text-muted-foreground">
          {targets.length} selected
        </span>
        <Button variant="ghost" size="sm" onClick={onClear} disabled={targets.length === 0}>
          <Trash2Icon data-icon="inline-start" />
          Clear
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {launchError && (
          <Alert variant="destructive" className="mb-3">
            <AlertCircleIcon aria-hidden="true" />
            <AlertTitle>Could not start every run</AlertTitle>
            <AlertDescription>{launchError}</AlertDescription>
          </Alert>
        )}
        {targets.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Select themes or skills from the map or outline.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {targets.map((target) => {
              const state = stateOf(target.kind, target.key);
              const retryable = state === "failed" || state === "cancelled";
              return (
                <li key={targetId(target)} className="rounded-md border bg-background px-4 py-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-medium">{target.label ?? target.key}</p>
                        <Badge variant="outline">
                          {target.kind === "theme" ? "Theme" : "Skill"}
                        </Badge>
                      </div>
                      <div className="mt-1.5">
                        <Status state={state} />
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      {retryable && (
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={`Retry ${target.label ?? target.key}`}
                          onClick={() => onRetry(target)}
                        >
                          <RefreshCwIcon data-icon="inline-start" aria-hidden="true" />
                        </Button>
                      )}
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Remove ${target.label ?? target.key}`}
                        onClick={() => onRemove(target)}
                      >
                        <XIcon data-icon="inline-start" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="border-t p-5">
        <Button
          className="w-full"
          disabled={launchableTargets.length === 0 || generating}
          onClick={() => onGenerateAll(launchableTargets)}
        >
          {generating ? <Spinner data-icon="inline-start" /> : <FlaskConicalIcon data-icon="inline-start" />}
          {generating ? "Starting…" : "Generate all"}
        </Button>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Runs continue independently after launch.
        </p>
      </div>
    </div>
  );
}

interface SelectionTrayProps {
  targets: SuggestionTarget[];
  stateOf: (kind: "skill" | "theme", key: string) => SuggestionState;
  onRemove: (target: SuggestionTarget) => void;
  onClear: () => void;
  onGenerateAll: (targets: SuggestionTarget[]) => void;
  onRetry: (target: SuggestionTarget) => void;
  generating: boolean;
  launchError: string | null;
}

export function SelectionTray(props: SelectionTrayProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <aside
        data-testid="desktop-selection-tray"
        aria-labelledby="selection-tray-title"
        className="sticky top-4 hidden max-h-[calc(100vh-2rem)] min-h-96 flex-col border bg-card xl:flex"
      >
        <div className="border-b px-5 py-5">
          <h2 id="selection-tray-title" className="text-sm font-semibold">
            Research selection
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Generate verified guidance for selected targets.
          </p>
        </div>
        <TrayContents {...props} />
      </aside>

      {props.targets.length > 0 && (
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            render={
              <Button className="fixed right-4 bottom-4 z-40 shadow-lg xl:hidden" />
            }
            aria-label="Open selection tray"
          >
            <FlaskConicalIcon data-icon="inline-start" />
            Selection ({props.targets.length})
          </SheetTrigger>
          <SheetContent side="bottom" className="max-h-[85vh] gap-0 xl:hidden">
            <SheetHeader className="border-b pr-12">
              <SheetTitle>Research selection</SheetTitle>
              <SheetDescription>
                Generate verified guidance for selected themes and skills.
              </SheetDescription>
            </SheetHeader>
            <TrayContents {...props} />
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}
