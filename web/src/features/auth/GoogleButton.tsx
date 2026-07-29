import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, unwrap } from "@/lib/api/client";

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4">
      <path fill="#4285F4" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.8 3-4.3 3-7.3Z" />
      <path fill="#34A853" d="M12 22c2.7 0 5-.9 6.6-2.4L15.4 17c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22Z" />
      <path fill="#FBBC05" d="M6.4 13.9A6 6 0 0 1 6.1 12c0-.7.1-1.3.3-1.9V7.5H3.1A10 10 0 0 0 2 12c0 1.6.4 3.1 1.1 4.5l3.3-2.6Z" />
      <path fill="#EA4335" d="M12 6c1.5 0 2.8.5 3.8 1.5l2.9-2.8A9.7 9.7 0 0 0 12 2a10 10 0 0 0-8.9 5.5l3.3 2.6A6 6 0 0 1 12 6Z" />
    </svg>
  );
}

export function GoogleButton({
  mode,
  invite,
  disabledReason,
}: {
  mode: "login" | "register";
  invite?: string;
  disabledReason?: string;
}) {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => unwrap(api.GET("/api/health")),
    staleTime: 60_000,
  });
  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.GET("/api/auth/google/start", {
          params: { query: { mode, ...(invite ? { invite } : {}) } },
        }),
      ),
    onSuccess: ({ authUrl }) => window.location.assign(authUrl),
  });
  const reason =
    disabledReason ??
    (health.isPending
      ? "Checking Google sign-in availability…"
      : health.data?.googleOauthConfigured
        ? undefined
        : "Google sign-in is not configured on this server.");
  const button = (
    <Button
      type="button"
      variant="outline"
      className="w-full"
      disabled={Boolean(reason) || start.isPending}
      onClick={() => start.mutate()}
    >
      {start.isPending ? <Spinner data-icon="inline-start" /> : <GoogleMark />}
      Continue with Google
    </Button>
  );
  return (
    <div>
      {reason ? (
        <Tooltip>
          <TooltipTrigger render={<span className="block" />}>{button}</TooltipTrigger>
          <TooltipContent>{reason}</TooltipContent>
        </Tooltip>
      ) : (
        button
      )}
      {start.isError ? <p className="mt-2 text-xs text-destructive" role="alert">{start.error.message}</p> : null}
    </div>
  );
}
