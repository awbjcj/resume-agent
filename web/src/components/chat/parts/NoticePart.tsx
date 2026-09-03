import { TriangleAlert } from "lucide-react";

export function NoticePart({ message }: { message: string }) {
  return (
    <p
      data-testid="chat-part-notice"
      className="tone-panel flex items-start gap-2 rounded-lg p-2.5 text-xs leading-relaxed"
      data-tone="warning"
    >
      <TriangleAlert className="tone-accent mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </p>
  );
}
