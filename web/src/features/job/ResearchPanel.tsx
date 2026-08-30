import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function ResearchPanelHeader({
  titleId,
  icon,
  eyebrow,
  title,
  description,
  context,
  action,
}: {
  titleId: string;
  icon: ReactNode;
  eyebrow: ReactNode;
  title: ReactNode;
  description: ReactNode;
  context?: ReactNode;
  action: ReactNode;
}) {
  return (
    <Card className="gap-0 p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {icon}
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              {eyebrow}
            </p>
            <h2 id={titleId} className="mt-1 font-heading text-xl font-semibold">
              {title}
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
              {description}
            </p>
            {context && (
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {context}
              </p>
            )}
          </div>
        </div>
        <div className="w-full shrink-0 sm:w-auto">{action}</div>
      </div>
    </Card>
  );
}

export function ResearchNotice({
  icon,
  children,
  className,
  role = "status",
}: {
  icon: ReactNode;
  children: ReactNode;
  className?: string;
  role?: "alert" | "status";
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border px-4 py-3 text-sm",
        className,
      )}
      role={role}
      aria-live={role === "alert" ? "assertive" : "polite"}
    >
      <span className="mt-0.5 shrink-0" aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
