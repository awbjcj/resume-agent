import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

export function TextPart({ text, caret = false }: { text: string; caret?: boolean }) {
  return (
    <div data-testid="chat-part-text" className="prose prose-sm max-w-none dark:prose-invert">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{text}</ReactMarkdown>
      {caret ? (
        <span
          aria-hidden="true"
          className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-foreground align-text-bottom"
        />
      ) : null}
    </div>
  );
}
