import { useRef } from "react";
import { FileUp, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

import {
  useDeleteSource,
  usePatchSource,
  useSkeleton,
  useSources,
  useUploadSource,
} from "./use-sources";

const MODES = ["literal", "synthesis"] as const;

// Matches the visual weight of components/ui/select's SelectTrigger, but stays
// a real <select> — the anchor/mode editors need native selection behavior
// (keyboard, userEvent.selectOptions) that a popover-based listbox doesn't give.
const nativeSelectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-xs outline-none " +
  "transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 " +
  "dark:bg-input/30 dark:hover:bg-input/50";

const STATUS_VARIANT: Record<string, "secondary" | "outline"> = {
  cached: "secondary",
};

function statusLabel(status: string): string {
  return status.replace(/-/g, " ");
}

export function SourceManager() {
  const { data: sources, isLoading } = useSources();
  const { data: skeleton } = useSkeleton();
  const upload = useUploadSource();
  const patch = usePatchSource();
  const remove = useDeleteSource();
  const fileInput = useRef<HTMLInputElement>(null);

  if (isLoading || !sources) return <Skeleton className="h-32 w-full" />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium">Source documents</div>
          <p className="text-sm text-muted-foreground">
            Resumes extract literally; decks and write-ups are synthesized and
            verified against their own text.
          </p>
        </div>
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md,.pptx,.xlsx,.html"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate({ file });
            e.target.value = "";
          }}
        />
        <Button
          variant="outline"
          disabled={upload.isPending}
          onClick={() => fileInput.current?.click()}
        >
          <FileUp data-icon="inline-start" aria-hidden="true" />
          Add source
        </Button>
      </div>

      {sources.length === 0 ? (
        <Empty>No sources yet — add your resume first; it becomes the primary.</Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead>Anchor</TableHead>
              <TableHead>Fragment</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sources.map((source) => (
              <TableRow key={source.id}>
                <TableCell className="font-medium">{source.filename}</TableCell>
                <TableCell>
                  {source.primary ? (
                    <Badge variant="secondary">Primary</Badge>
                  ) : (
                    <select
                      aria-label={`mode for ${source.filename}`}
                      className={nativeSelectClass}
                      value={source.mode}
                      onChange={(e) =>
                        patch.mutate({ id: source.id, mode: e.target.value as "literal" | "synthesis" })
                      }
                    >
                      {MODES.map((mode) => (
                        <option key={mode} value={mode}>{mode}</option>
                      ))}
                    </select>
                  )}
                </TableCell>
                <TableCell>
                  {source.mode === "synthesis" ? (
                    <select
                      aria-label={`anchor for ${source.filename}`}
                      className={nativeSelectClass}
                      value={source.anchor ?? ""}
                      onChange={(e) =>
                        patch.mutate({ id: source.id, anchor: e.target.value || null })
                      }
                    >
                      <option value="">Auto-anchor</option>
                      {(skeleton ?? []).map((entry) => (
                        <option key={entry.id} value={entry.id}>{entry.label}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[source.fragmentStatus] ?? "outline"}>
                    {statusLabel(source.fragmentStatus)}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  {!source.primary ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove ${source.filename}`}
                      onClick={() => remove.mutate(source.id)}
                    >
                      <Trash2 data-icon="inline-start" aria-hidden="true" />
                      Remove
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
