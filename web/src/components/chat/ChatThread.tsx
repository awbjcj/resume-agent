import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ChatPart } from "@/lib/chat/events";
import { cn } from "@/lib/utils";

import { ChatMessage } from "./ChatMessage";

export interface ChatThreadMessage {
  id: string;
  role: "user" | "assistant";
  parts: ChatPart[];
}

const STICK_THRESHOLD_PX = 64;

export function ChatThread({
  messages,
  streaming,
  streamingActive = true,
  showReasoning = true,
  renderAfter,
  className,
  assistantName = "Assistant",
  assistantIcon,
}: {
  messages: ChatThreadMessage[];
  streaming: ChatPart[] | null;
  streamingActive?: boolean;
  showReasoning?: boolean;
  renderAfter?: (message: ChatThreadMessage) => ReactNode;
  className?: string;
  assistantName?: string;
  assistantIcon?: ReactNode;
}) {
  const viewport = useRef<HTMLDivElement | null>(null);
  const [stuck, setStuck] = useState(true);
  const onScroll = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    setStuck(node.scrollHeight - node.clientHeight - node.scrollTop <= STICK_THRESHOLD_PX);
  }, []);
  const jump = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    setStuck(true);
  }, []);
  useEffect(() => {
    if (!stuck) return;
    const frame = requestAnimationFrame(() => {
      if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, streaming, stuck]);

  return (
    <div className={cn("relative min-h-0 flex-1", className)}>
      <div
        ref={viewport}
        data-testid="chat-viewport"
        onScroll={onScroll}
        className="chat-scroll-fade h-full overflow-y-auto overscroll-contain px-1"
      >
        <div className="w-full space-y-6 py-4 sm:px-2 sm:py-5">
          {messages.map((message) => (
            <div key={message.id}>
              <ChatMessage
                message={message}
                showReasoning={showReasoning}
                assistantName={assistantName}
                assistantIcon={assistantIcon}
              />
              {renderAfter?.(message)}
            </div>
          ))}
          {streaming?.length ? (
            <div role="status" aria-label="Assistant response streaming">
              <ChatMessage
                message={{ id: "streaming", role: "assistant", parts: streaming }}
                showReasoning={showReasoning}
                streaming={streamingActive}
                assistantName={assistantName}
                assistantIcon={assistantIcon}
              />
            </div>
          ) : null}
        </div>
      </div>
      {!stuck ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={jump}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-md"
        >
          <ArrowDown className="size-4" aria-hidden="true" />
          Jump to latest
        </Button>
      ) : null}
    </div>
  );
}
