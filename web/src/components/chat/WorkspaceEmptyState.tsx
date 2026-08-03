import type { ComponentType, ReactNode } from "react";
import { ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface WorkspaceTutorialStep {
  icon: ComponentType<{ className?: string; "aria-hidden"?: "true" }>;
  title: string;
  description: string;
}

export function WorkspaceEmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  busy = false,
  steps,
  actionIcon,
}: {
  icon: ComponentType<{ className?: string; "aria-hidden"?: "true" }>;
  title: string;
  description: string;
  actionLabel: string;
  onAction: () => void;
  busy?: boolean;
  steps: WorkspaceTutorialStep[];
  actionIcon?: ReactNode;
}) {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center px-4 py-8 text-center sm:px-8">
      <div className="flex size-12 items-center justify-center rounded-xl border bg-background text-primary shadow-sm">
        <Icon className="size-5" aria-hidden="true" />
      </div>
      <h2 className="mt-4 text-xl font-semibold tracking-[-0.02em]">{title}</h2>
      <p className="mt-1.5 max-w-xl text-sm leading-6 text-muted-foreground">{description}</p>
      <Button className="mt-5" disabled={busy} onClick={onAction}>
        {actionIcon}
        {actionLabel}
        {!actionIcon ? <ArrowRight aria-hidden="true" /> : null}
      </Button>
      <ol className="mt-8 grid w-full gap-3 text-left md:grid-cols-3">
        {steps.map((step, index) => {
          const StepIcon = step.icon;
          return (
            <li key={step.title} className="rounded-xl border bg-card/70 p-4">
              <div className="flex items-center justify-between">
                <span className="flex size-8 items-center justify-center rounded-lg bg-primary/8 text-primary">
                  <StepIcon className="size-4" aria-hidden="true" />
                </span>
                <span className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">0{index + 1}</span>
              </div>
              <h3 className="mt-3 text-sm font-semibold">{step.title}</h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{step.description}</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
