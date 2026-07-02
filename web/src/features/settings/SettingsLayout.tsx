import { NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

export const SETTINGS_NAV = [
  { to: "/settings/profile", label: "Profile & documents" },
  { to: "/settings/search", label: "Search" },
  { to: "/settings/sources", label: "Sources" },
  { to: "/settings/keys", label: "API keys" },
  { to: "/settings/review", label: "Review panel" },
  { to: "/settings/rendering", label: "Rendering" },
  { to: "/settings/pruning", label: "Pruning" },
  { to: "/settings/style-guide", label: "Style guide" },
] as const;

export function SettingsLayout() {
  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:gap-10">
      <nav aria-label="Settings" className="lg:w-56 lg:shrink-0">
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Settings
        </div>
        <ul className="mt-3 flex flex-row flex-wrap gap-1 lg:flex-col">
          {SETTINGS_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "block rounded-lg px-3 py-2 text-sm hover:bg-accent",
                    isActive && "bg-accent font-medium",
                  )
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 flex-1 max-w-3xl">
        <Outlet />
      </div>
    </div>
  );
}
