import type { ReactNode } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";

// The Google callback runs outside the SPA, so its only channel back is a
// redirect carrying ?error=<code>. Every code the callback can emit needs an
// entry here: an unmapped one renders the fallback rather than nothing, because
// a silently blank auth form is indistinguishable from a broken server.
const CALLBACK_ERRORS: Record<string, string> = {
  denied: "Google sign-in was cancelled.",
  invalid_state: "That Google sign-in link expired. Please try again.",
  unavailable: "Google sign-in is unavailable on this server right now.",
  exchange_failed: "Google sign-in didn’t complete. Please try again.",
  disabled: "This account is disabled. Contact your administrator.",
  google_conflict:
    "That Google account is already linked to a different account. Sign in with your password instead.",
  unverified_google:
    "Google hasn’t verified that email address, so it can’t be linked to an account.",
  invite_invalid:
    "That invitation code is invalid, expired, or already used. Ask your administrator for a new one.",
  conflict: "Your account couldn’t be created. Please try again.",
};

const FALLBACK = "Sign-in didn’t complete. Please try again.";

export function callbackErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return CALLBACK_ERRORS[code] ?? FALLBACK;
}

export function AuthNotice({
  tone,
  children,
}: {
  tone: "info" | "error";
  children: ReactNode;
}) {
  return (
    <Alert
      className="mb-5"
      variant={tone === "error" ? "destructive" : "default"}
      role={tone === "error" ? "alert" : "status"}
    >
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}
