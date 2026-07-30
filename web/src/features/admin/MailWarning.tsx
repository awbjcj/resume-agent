import { useQuery } from "@tanstack/react-query";
import { MailWarningIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { api, unwrap } from "@/lib/api/client";

export function MailWarning() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => unwrap(api.GET("/api/health")), staleTime: 60_000 });
  if (health.isPending || health.data?.mailConfigured !== false) return null;
  return <Alert variant="destructive"><MailWarningIcon aria-hidden="true" /><AlertTitle>Email delivery is not configured</AlertTitle><AlertDescription>Verification and password-recovery messages are only logged. Configure SMTP before inviting members.</AlertDescription></Alert>;
}
