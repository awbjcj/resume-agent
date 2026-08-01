import { Send, Square } from "lucide-react";

import { TranscribeButton } from "@/components/TranscribeButton";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  ariaLabel = "Message",
  placeholder = "Type your reply…",
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  ariaLabel?: string;
  placeholder?: string;
}) {
  return (
    <div className="flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm">
      <Textarea
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (!busy && value.trim()) onSend();
          }
        }}
        placeholder={placeholder}
        rows={2}
        disabled={busy}
        className="min-h-14 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
      />
      <TranscribeButton onText={(text) => onChange(value ? `${value} ${text}` : text)} disabled={busy} />
      {busy ? (
        <Button size="icon" variant="secondary" onClick={onStop} aria-label="Stop generating">
          <Square className="size-4" aria-hidden="true" />
        </Button>
      ) : (
        <Button size="icon" onClick={onSend} disabled={!value.trim()} aria-label="Send message">
          <Send className="size-4" aria-hidden="true" />
        </Button>
      )}
    </div>
  );
}
