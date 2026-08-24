import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

/**
 * One list of section names shared by every admin page, so a section is called
 * the same thing wherever it is linked from and the current page can never be
 * labelled differently than the tab that leads back to it.
 */
const ADMIN_SECTIONS = [
  { to: "/admin", label: "Access & data" },
  { to: "/admin/quotas", label: "Cost quotas" },
  { to: "/admin/routing", label: "Provider routing" },
] as const;

export type AdminSection = (typeof ADMIN_SECTIONS)[number]["to"];

export function AdminSectionNav({ current }: { current: AdminSection }) {
  return (
    <nav aria-label="Administration sections" className="-mt-5 flex flex-wrap gap-2">
      {ADMIN_SECTIONS.map((section) => {
        const isCurrent = section.to === current;
        return (
          <Button
            key={section.to}
            nativeButton={false}
            variant={isCurrent ? "secondary" : "outline"}
            size="sm"
            aria-current={isCurrent ? "page" : undefined}
            render={<Link to={section.to} />}
          >
            {section.label}
          </Button>
        );
      })}
    </nav>
  );
}
