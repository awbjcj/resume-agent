import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import { prettifyPlainText } from "@/lib/format/prettify";

// Renders a job description. New rows are markdown; legacy rows are flat text.
// remark-gfm renders real lists/headings; remark-breaks preserves legacy newlines.
export function JdBody({ text }: { text: string }) {
  return (
    <div className="jd-markdown mt-3 rounded-xl border bg-background/60 p-5 text-[15px] leading-7">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
        {prettifyPlainText(text)}
      </ReactMarkdown>
    </div>
  );
}
