import type { ReactNode } from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";

export function AuthLayout({
  title,
  description,
  icon,
  children,
  footer,
}: {
  title: string;
  description: string;
  icon?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-muted/20">
      <aside
        data-slot="auth-brand"
        aria-hidden="true"
        className="relative hidden w-[55%] overflow-hidden bg-primary p-12 text-primary-foreground lg:flex lg:flex-col lg:justify-between"
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,color-mix(in_oklab,var(--primary-foreground)_22%,transparent),transparent_55%)]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,color-mix(in_oklab,var(--primary-foreground)_8%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_oklab,var(--primary-foreground)_8%,transparent)_1px,transparent_1px)] bg-[size:3rem_3rem]" />
        <p className="relative text-lg font-semibold tracking-tight">Resume Agent</p>
        <div className="relative max-w-md">
          <p className="text-3xl font-semibold leading-tight tracking-tight">
            Every bullet traces back to a fact you actually wrote.
          </p>
          <p className="mt-4 text-sm opacity-80">
            Discover roles, tailor with provenance, and track every application from one
            workspace.
          </p>
        </div>
        <p className="relative text-xs opacity-70">Your private command center.</p>
      </aside>
      <main className="flex w-full items-center justify-center p-4 sm:p-8 lg:w-[45%]">
        <Card className="w-full max-w-md shadow-lg shadow-primary/5">
          <CardHeader>
            {icon ? (
              <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                {icon}
              </div>
            ) : null}
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </CardHeader>
          <CardContent>
            {children}
            {footer ? <div className="mt-6 text-sm">{footer}</div> : null}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
