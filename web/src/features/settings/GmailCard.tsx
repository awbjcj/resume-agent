import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useGmailConnect,
  useGmailDisconnect,
  useGmailStatus,
} from "./use-gmail";

export function GmailCard() {
  const { data: status, isLoading } = useGmailStatus();
  const connect = useGmailConnect();
  const disconnect = useGmailDisconnect();

  return (
    <section className="rounded-lg border p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Mail className="size-4" aria-hidden="true" /> Gmail
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {isLoading
              ? "Checking connection…"
              : status?.connected
                ? status.draftCapable
                  ? `Connected (${status.clientSource} client) — sync and drafts enabled.`
                  : `Connected (${status.clientSource} client) — reconnect to enable drafts.`
                : "Not connected. Connect to sync application status and draft emails."}
          </p>
        </div>
        {status?.connected ? (
          <div className="flex gap-2">
            {!status.draftCapable && (
              <Button
                size="sm"
                variant="outline"
                disabled={connect.isPending}
                onClick={() => connect.mutate()}
              >
                Reconnect
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate()}
            >
              Disconnect
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            disabled={connect.isPending || isLoading}
            onClick={() => connect.mutate()}
          >
            Connect Gmail
          </Button>
        )}
      </div>
    </section>
  );
}
