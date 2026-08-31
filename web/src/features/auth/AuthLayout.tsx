import type { ReactNode } from "react";
import { ArrowRight, BadgeCheck, FileText, Search, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
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
  const { t } = useTranslation();
  return (
    <div className="auth-shell flex min-h-svh bg-background">
      <aside
        data-slot="auth-brand"
        aria-hidden="true"
        className="auth-brand-panel sticky top-0 hidden h-svh w-[54%] overflow-hidden px-10 py-9 text-white lg:flex lg:flex-col xl:px-12 xl:py-10 2xl:w-[57%] 2xl:px-14"
      >
        <div className="auth-brand-header relative z-10 flex shrink-0 items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-white/15 bg-white/10 shadow-[0_12px_34px_-18px_rgba(91,216,231,0.85)] backdrop-blur-md">
            <Sparkles className="size-4.5" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-tight">Résumé Tailor Harness</p>
            <p className="mt-0.5 text-[0.68rem] font-medium uppercase tracking-[0.22em] text-white/55">
              {t("auth.privateCareerWorkspace")}
            </p>
          </div>
        </div>

        <div
          data-slot="auth-brand-story"
          className="auth-brand-story relative z-10 mx-auto flex min-h-0 w-full max-w-[46rem] flex-1 flex-col justify-center py-8"
        >
          <div data-slot="auth-brand-copy" className="auth-brand-copy max-w-[39rem]">
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-cyan-200/75">
              {t("auth.evidenceLedOperations")}
            </p>
            <h2 className="auth-brand-copy-heading mt-4 text-[2.65rem] font-semibold leading-[1.02] tracking-[-0.045em] xl:text-[3.2rem]">
              {t("auth.brandPromise")}
            </h2>
            <p className="auth-brand-copy-summary mt-5 max-w-[35rem] text-[0.95rem] leading-7 text-white/68">
              {t("auth.brandSummary")}
            </p>
          </div>

          <div data-slot="auth-brand-visual" className="auth-workspace-preview mt-9">
            <div className="auth-preview-bar flex items-center justify-between border-b border-white/10 px-5 py-3.5">
              <div className="flex items-center gap-2.5 text-xs font-medium text-white/76">
                <span className="size-2 rounded-full bg-cyan-300 shadow-[0_0_0_4px_rgba(103,232,249,0.08)]" />
                {t("auth.privateCareerWorkspace")}
              </div>
              <div className="flex items-center gap-1.5 text-[0.68rem] font-medium text-emerald-200/80">
                <ShieldCheck className="size-3.5" aria-hidden="true" />
                {t("auth.secureWorkspace")}
              </div>
            </div>

            <div className="grid grid-cols-[minmax(0,1.18fr)_minmax(12rem,0.82fr)] gap-4 p-4 xl:gap-5 xl:p-5">
              <div className="auth-evidence-document rounded-xl border border-white/10 bg-white/[0.055] p-4 xl:p-5">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-2 text-xs font-semibold text-white/86">
                    <FileText className="size-4 text-cyan-200/80" aria-hidden="true" />
                    {t("auth.tailor")}
                  </div>
                  <BadgeCheck className="size-4 text-emerald-300/85" aria-hidden="true" />
                </div>
                <div className="mt-5 h-2 w-2/5 rounded-full bg-white/65" />
                <div className="mt-2 h-1.5 w-1/4 rounded-full bg-white/18" />
                <div className="mt-6 space-y-3">
                  <div className="auth-evidence-line"><span /><i /></div>
                  <div className="auth-evidence-line"><span /><i /></div>
                  <div className="auth-evidence-line"><span /><i /></div>
                </div>
                <div className="mt-5 flex gap-2">
                  <span className="h-5 w-16 rounded-full border border-cyan-200/15 bg-cyan-200/8" />
                  <span className="h-5 w-20 rounded-full border border-cyan-200/15 bg-cyan-200/8" />
                </div>
              </div>

              <div className="auth-evidence-flow flex flex-col justify-center rounded-xl border border-white/10 bg-[#041820]/48 p-4">
                <div className="auth-flow-step">
                  <span><Search aria-hidden="true" /></span>
                  <strong>{t("auth.discover")}</strong>
                </div>
                <ArrowRight className="auth-flow-arrow" aria-hidden="true" />
                <div className="auth-flow-step is-current">
                  <span><FileText aria-hidden="true" /></span>
                  <strong>{t("auth.tailor")}</strong>
                </div>
                <ArrowRight className="auth-flow-arrow" aria-hidden="true" />
                <div className="auth-flow-step">
                  <span><BadgeCheck aria-hidden="true" /></span>
                  <strong>{t("auth.track")}</strong>
                </div>
              </div>
            </div>

            <div className="auth-preview-note flex items-center gap-2.5 border-t border-white/10 px-5 py-3 text-[0.7rem] leading-relaxed text-white/48">
              <span className="h-px w-5 shrink-0 bg-cyan-200/35" />
              {t("auth.sourceMaterialPromise")}
            </div>
          </div>
        </div>
      </aside>
      <main className="auth-surface relative flex min-h-svh w-full items-center justify-center px-4 py-6 sm:px-8 sm:py-10 lg:w-[46%] 2xl:w-[43%]">
        <div className="absolute right-4 top-4 sm:right-8 sm:top-8">
          <LanguageSwitcher />
        </div>
        <div className="w-full max-w-[30rem]">
          <div className="mb-6 flex items-center gap-3 px-1 lg:hidden">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[0_10px_28px_-14px_color-mix(in_oklab,var(--primary),transparent_28%)]">
              <Sparkles className="size-4.5" aria-hidden="true" />
            </div>
            <div>
              <div className="text-sm font-semibold leading-tight tracking-tight">Résumé Tailor Harness</div>
              <div className="mt-0.5 text-[0.68rem] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {t("auth.privateCareerWorkspace")}
              </div>
            </div>
          </div>
          <Card className="auth-card w-full gap-0 rounded-2xl py-0 shadow-card-raised ring-foreground/9">
            <CardHeader className="gap-0 px-6 pb-5 pt-6 sm:px-7 sm:pt-7">
              <div className="mb-5 flex items-center justify-between gap-3">
                {icon ? (
                  <div className="flex size-11 items-center justify-center rounded-xl border border-primary/15 bg-accent text-accent-foreground shadow-[inset_0_1px_0_color-mix(in_oklab,var(--background),transparent_18%)] [&_svg]:size-5">
                    {icon}
                  </div>
                ) : <span />}
                <div className="flex items-center gap-1.5 rounded-full border border-border/80 bg-muted/55 px-2.5 py-1 text-[0.68rem] font-medium text-muted-foreground">
                  <ShieldCheck className="size-3.5 text-primary" aria-hidden="true" />
                  {t("auth.secureWorkspace")}
                </div>
              </div>
              <h1 className="text-[1.75rem] font-semibold leading-tight tracking-[-0.03em]">{title}</h1>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p>
            </CardHeader>
            <CardContent className="px-6 pb-6 sm:px-7 sm:pb-7">
              {children}
              {footer ? <div className="mt-6 border-t border-border/70 pt-5 text-sm">{footer}</div> : null}
            </CardContent>
          </Card>
          <p className="mt-5 px-2 text-center text-xs leading-relaxed text-muted-foreground/80">
            {t("auth.sourceMaterialPromise")}
          </p>
        </div>
      </main>
    </div>
  );
}
