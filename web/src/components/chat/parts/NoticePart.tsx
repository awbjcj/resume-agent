import { TriangleAlert } from "lucide-react";

export function NoticePart({ message }: { message: string }) {
  return (
    <p
      data-testid="chat-part-notice"
      className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/8 p-2.5 text-xs leading-relaxed text-amber-900 dark:text-amber-200"
    >
      <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </p>
  );
}
