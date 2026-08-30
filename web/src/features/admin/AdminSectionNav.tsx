import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * One list of section names shared by every admin page, so a section is called
 * the same thing wherever it is linked from and the current page can never be
 * labelled differently than the tab that leads back to it.
 */
const ADMIN_SECTIONS = [
  { to: "/admin", labelKey: "admin.sections.accessData" },
  { to: "/admin/quotas", labelKey: "admin.sections.costQuotas" },
  { to: "/admin/routing", labelKey: "admin.sections.providerRouting" },
] as const;

export type AdminSection = (typeof ADMIN_SECTIONS)[number]["to"];

export function AdminSectionNav({ current }: { current: AdminSection }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("admin.sections.navigation")} className="shell-action-rail -mt-5 flex flex-nowrap gap-2 pb-1">
      {ADMIN_SECTIONS.map((section) => {
        const isCurrent = section.to === current;
        return (
          <Button
            key={section.to}
            className="shrink-0"
            nativeButton={false}
            variant={isCurrent ? "secondary" : "outline"}
            size="sm"
            aria-current={isCurrent ? "page" : undefined}
            render={<Link to={section.to} />}
          >
            {t(section.labelKey)}
          </Button>
        );
      })}
    </nav>
  );
}
