import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useSetupStatus } from "@/features/settings/use-setup-status";

export function SetupGate({ children }: { children: ReactNode }) {
  const { data, isError } = useSetupStatus();
  if (isError) return <>{children}</>; // fail open — never lock a working app
  if (!data) return <>{children}</>;   // loading: render normally, no flash-gate
  const dismissed = localStorage.getItem("resume-agent-setup-dismissed") === "1";
  if (!data.complete && !dismissed) return <Navigate to="/setup" replace />;
  return <>{children}</>;
}
