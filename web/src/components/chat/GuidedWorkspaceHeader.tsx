import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type GuidedWorkspaceTone = "coach" | "interview" | "scout";

export function GuidedWorkspaceHeader({
  tone,
  icon,
  eyebrow,
  title,
  description,
  meta,
  actions,
  className,
}: {
  tone: GuidedWorkspaceTone;
  icon: ReactNode;
  eyebrow: string;
  title: ReactNode;
  description: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      data-tone={tone}
      className={cn(
        "guided-workspace-hero relative overflow-hidden rounded-2xl p-5 shadow-card ring-1 ring-foreground/10 sm:p-6",
        className,
      )}
    >
      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-current/10 bg-background/75 text-(--workspace-tone) shadow-sm [&_svg]:size-5" aria-hidden="true">
            {icon}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-[0.16em] text-(--workspace-tone) uppercase">{eyebrow}</p>
            <h1 className="mt-1 text-3xl leading-tight font-semibold tracking-[-0.03em] sm:text-4xl">{title}</h1>
            <div className="mt-2 max-w-[72ch] text-sm leading-relaxed text-muted-foreground sm:text-base">{description}</div>
            {meta ? <div className="mt-4 flex flex-wrap items-center gap-2">{meta}</div> : null}
          </div>
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">{actions}</div> : null}
      </div>
    </header>
  );
}
