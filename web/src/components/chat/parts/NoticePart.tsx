import { TriangleAlert } from "lucide-react";

export function NoticePart({ message }: { message: string }) {
  return (
    <p
      data-testid="chat-part-notice"
      className="flex items-start gap-2 rounded-md bg-amber-500/10 p-2 text-xs text-amber-900 dark:text-amber-200"
    >
      <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </p>
  );
}
