import type { ReactNode } from "react";
import { ShieldCheck, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import authEvidenceVisual from "@/assets/auth-evidence-command-center.webp";
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
        className="auth-brand-panel sticky top-0 hidden h-svh w-[54%] overflow-hidden p-10 text-white lg:flex lg:flex-col xl:p-12 2xl:w-[57%] 2xl:p-14"
      >
        <div className="relative z-10 flex shrink-0 items-center gap-3">
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
          data-slot="auth-brand-visual"
          className="auth-brand-visual relative mt-3 flex min-h-0 flex-1 items-center justify-center overflow-hidden"
        >
          <img
            className="auth-brand-art h-full w-auto max-w-full object-contain object-center"
            src={authEvidenceVisual}
            alt=""
          />
        </div>

        <div
          data-slot="auth-brand-copy"
          className="auth-brand-copy relative z-10 mt-3 w-full max-w-xl shrink-0 rounded-2xl border border-white/12 bg-[#061d26]/82 p-6 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.72)] xl:p-7"
        >
          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-cyan-200/75">
            {t("auth.evidenceLedOperations")}
          </p>
          <p className="auth-brand-copy-heading mt-3 text-3xl font-semibold leading-[1.08] tracking-[-0.035em] xl:text-[2.35rem]">
            {t("auth.brandPromise")}
          </p>
          <p className="auth-brand-copy-summary mt-4 max-w-lg text-sm leading-relaxed text-white/68">
            {t("auth.brandSummary")}
          </p>
          <div className="auth-brand-copy-flow mt-6 flex items-center gap-2 text-[0.7rem] font-medium text-white/72">
            <span className="rounded-full border border-white/12 bg-white/7 px-3 py-1.5">{t("auth.discover")}</span>
            <span className="h-px w-5 bg-white/18" />
            <span className="rounded-full border border-white/12 bg-white/7 px-3 py-1.5">{t("auth.tailor")}</span>
            <span className="h-px w-5 bg-white/18" />
            <span className="rounded-full border border-white/12 bg-white/7 px-3 py-1.5">{t("auth.track")}</span>
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
