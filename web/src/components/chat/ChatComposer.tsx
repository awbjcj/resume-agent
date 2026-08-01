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
    // `items-end` plus a one-line `min-h-9` keeps the buttons on the same line
    // as the text: the Textarea carries `field-sizing-content`, so it starts at
    // exactly one button-height and grows downward with the content, with the
    // buttons staying pinned to the last line. A taller floor (the old
    // `min-h-14`) left a single line of text stranded at the top of the box
    // while the buttons sat at the bottom.
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
        rows={1}
        disabled={busy}
        className="max-h-56 min-h-9 flex-1 resize-none overflow-y-auto border-0 bg-transparent shadow-none focus-visible:ring-0"
      />
      <TranscribeButton onText={(text) => onChange(value ? `${value} ${text}` : text)} disabled={busy} />
      {busy ? (
        <Button size="icon-sm" variant="secondary" onClick={onStop} aria-label="Stop generating">
          <Square className="size-4" aria-hidden="true" />
        </Button>
      ) : (
        <Button size="icon-sm" onClick={onSend} disabled={!value.trim()} aria-label="Send message">
          <Send className="size-4" aria-hidden="true" />
        </Button>
      )}
    </div>
  );
}
