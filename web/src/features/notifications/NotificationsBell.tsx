import { useState } from "react";
import { Bell, Check, Inbox, Loader2, RefreshCw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { EmailDraftDialog } from "@/features/job/EmailDraftDialog";
import {
  useAcceptNotification,
  useDismissNotification,
  useGmailSync,
  useNotifications,
} from "./use-notifications";

export function NotificationsBell() {
  const { data: items = [], isLoading } = useNotifications();
  const accept = useAcceptNotification();
  const dismiss = useDismissNotification();
  const sync = useGmailSync();
  const [draftJobId, setDraftJobId] = useState<number | null>(null);
  const count = items.length;

  return (
    <>
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Notifications${count ? ` (${count} pending)` : ""}`}
            className="relative"
          >
            <Bell className="size-4" aria-hidden="true" />
            {count > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex min-w-5 items-center justify-center rounded-full bg-primary px-1 text-[0.68rem] font-semibold leading-5 text-primary-foreground">
                {count}
              </span>
            )}
          </Button>
        }
      />
      <PopoverContent align="end" className="w-[min(24rem,calc(100vw-2rem))] p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">Notifications</div>
            <div className="text-xs text-muted-foreground">
              Status proposals & follow-up reminders
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            {sync.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="size-4" aria-hidden="true" />
            )}
            Sync Gmail
          </Button>
        </div>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading notifications...</p>
        ) : count === 0 ? (
          <div className="rounded-lg border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground">
            <Inbox className="mb-2 size-4" aria-hidden="true" />
            Nothing pending.
          </div>
        ) : (
          <ul className="max-h-[24rem] space-y-2 overflow-y-auto pr-1">
            {items.map((item) => (
              <li key={item.id} className="rounded-lg border bg-background p-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium">
                      {item.kind === "follow_up"
                        ? `Follow up: ${item.company ?? "application"}`
                        : `Move to ${item.proposedStatus}`}
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {item.evidence}
                    </p>
                  </div>
                </div>
                <div className="mt-3 flex justify-end gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={dismiss.isPending}
                    onClick={() => dismiss.mutate(item.id)}
                  >
                    <X className="size-4" aria-hidden="true" />
                    Dismiss
                  </Button>
                  <Button
                    size="sm"
                    disabled={accept.isPending}
                    onClick={() => {
                      accept.mutate(item.id);
                      if (item.kind === "follow_up" && item.jobId != null) {
                        setDraftJobId(item.jobId);
                      }
                    }}
                  >
                    <Check className="size-4" aria-hidden="true" />
                    {item.kind === "follow_up" ? "Draft follow-up" : "Accept"}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
    {draftJobId != null && (
      <EmailDraftDialog
        jobId={draftJobId}
        defaultType="follow_up"
        open
        onOpenChange={(o) => !o && setDraftJobId(null)}
      />
    )}
    </>
  );
}
