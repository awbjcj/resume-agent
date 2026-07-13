import { useRef, useState } from "react";
import { FileUp, RefreshCw, Star, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

import {
  useDeleteSource,
  usePatchSource,
  useReplaceSource,
  useSkeleton,
  useSources,
  useSyncGithub,
  useUploadSources,
} from "./use-sources";
import { MaterialIntakeDialogs } from "./MaterialIntakeDialogs";

const MODES = ["literal", "synthesis"] as const;

// Matches the visual weight of components/ui/select's SelectTrigger, but stays
// a real <select> — the anchor/mode editors need native selection behavior
// (keyboard, userEvent.selectOptions) that a popover-based listbox doesn't give.
const nativeSelectClass =
  "h-8 rounded-lg border border-input bg-popover px-2 text-xs text-popover-foreground outline-none " +
  "[color-scheme:light] transition-colors focus-visible:border-ring focus-visible:ring-3 " +
  "focus-visible:ring-ring/50 dark:[color-scheme:dark]";
const nativeOptionClass = "bg-popover text-popover-foreground";

const STATUS_VARIANT: Record<string, "secondary" | "outline"> = {
  cached: "secondary",
};

function statusLabel(status: string): string {
  return status.replace(/-/g, " ");
}

export function SourceManager() {
  const { data: sources, isLoading } = useSources();
  const { data: skeleton } = useSkeleton();
  const upload = useUploadSources();
  const patch = usePatchSource();
  const remove = useDeleteSource();
  const replace = useReplaceSource();
  const syncGithub = useSyncGithub();
  const fileInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const [uploadMode, setUploadMode] = useState<(typeof MODES)[number]>("literal");
  const [uploadAnchor, setUploadAnchor] = useState("");
  const [replaceTargetId, setReplaceTargetId] = useState<string | null>(null);

  if (isLoading || !sources) return <Skeleton className="h-32 w-full" />;

  return (
    <div
      className="flex flex-col gap-4"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const files = Array.from(event.dataTransfer.files);
        if (files.length) {
          void upload.uploadAll(
            files,
            uploadMode,
            uploadMode === "synthesis" ? uploadAnchor || null : null,
          );
        }
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium">Source documents</div>
          <p className="text-sm text-muted-foreground">
            Upload files, add direct notes or public pages, and sync GitHub
            projects into one evidence-backed profile.
          </p>
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          className="hidden"
          accept=".pdf,.docx,.txt,.md,.pptx,.xlsx,.html"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) {
              void upload.uploadAll(
                files,
                uploadMode,
                uploadMode === "synthesis" ? uploadAnchor || null : null,
              );
            }
            e.target.value = "";
          }}
        />
        <input
          ref={replaceInput}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md,.pptx,.xlsx,.html"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file && replaceTargetId) {
              replace.mutate({ oldId: replaceTargetId, file });
            }
            e.target.value = "";
            setReplaceTargetId(null);
          }}
        />
        <div className="flex flex-wrap items-center justify-end gap-2">
          <MaterialIntakeDialogs />
          <Button
            variant="outline"
            disabled={syncGithub.isPending}
            onClick={() => syncGithub.mutate()}
          >
            {syncGithub.isPending ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <RefreshCw data-icon="inline-start" aria-hidden="true" />
            )}
            Sync GitHub
          </Button>
          <select
            aria-label="New source mode"
            className={nativeSelectClass}
            value={uploadMode}
            onChange={(e) => {
              const mode = e.target.value as (typeof MODES)[number];
              setUploadMode(mode);
              if (mode === "literal") setUploadAnchor("");
            }}
          >
            {MODES.map((mode) => (
              <option className={nativeOptionClass} key={mode} value={mode}>{mode}</option>
            ))}
          </select>
          {uploadMode === "synthesis" ? (
            <select
              aria-label="New source anchor"
              className={nativeSelectClass}
              value={uploadAnchor}
              onChange={(e) => setUploadAnchor(e.target.value)}
            >
              <option className={nativeOptionClass} value="">Auto-anchor</option>
              {(skeleton ?? []).map((entry) => (
                <option className={nativeOptionClass} key={entry.id} value={entry.id}>{entry.label}</option>
              ))}
            </select>
          ) : null}
          <Button
            variant="outline"
            onClick={() => fileInput.current?.click()}
          >
            <FileUp data-icon="inline-start" aria-hidden="true" />
            Add source
          </Button>
        </div>
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
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <span>{source.filename}</span>
                    {source.origin === "github" ? <Badge variant="outline">GitHub</Badge> : null}
                  </div>
                </TableCell>
                <TableCell>
                  {source.mode === "project" ? (
                    <Badge variant="secondary">Project</Badge>
                  ) : source.primary ? (
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
                        <option className={nativeOptionClass} key={mode} value={mode}>{mode}</option>
                      ))}
                    </select>
                  )}
                </TableCell>
                <TableCell>
                  {source.mode === "synthesis" && source.origin !== "github" ? (
                    <select
                      aria-label={`anchor for ${source.filename}`}
                      className={nativeSelectClass}
                      value={source.anchor ?? ""}
                      onChange={(e) =>
                        patch.mutate({ id: source.id, anchor: e.target.value || null })
                      }
                    >
                      <option className={nativeOptionClass} value="">Auto-anchor</option>
                      {(skeleton ?? []).map((entry) => (
                        <option className={nativeOptionClass} key={entry.id} value={entry.id}>{entry.label}</option>
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
                <TableCell>
                  {source.origin === "github" ? (
                    <span className="block text-right text-xs text-muted-foreground">
                      Synced
                    </span>
                  ) : source.primary ? (
                    <div className="flex justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={replace.isPending}
                        aria-label={`Replace ${source.filename}`}
                        onClick={() => {
                          setReplaceTargetId(source.id);
                          replaceInput.current?.click();
                        }}
                      >
                        <RefreshCw data-icon="inline-start" aria-hidden="true" />
                        Replace
                      </Button>
                    </div>
                  ) : (
                    <div className="flex flex-wrap items-center justify-end gap-1">
                      {source.mode === "project" ? (
                        <span className="text-xs text-muted-foreground">Read-only</span>
                      ) : source.mode === "literal" ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Make ${source.filename} primary`}
                          onClick={() => patch.mutate({ id: source.id, primary: true })}
                        >
                          <Star data-icon="inline-start" aria-hidden="true" />
                          Primary
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove ${source.filename}`}
                        onClick={() => remove.mutate(source.id)}
                      >
                        <Trash2 data-icon="inline-start" aria-hidden="true" />
                        Remove
                      </Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
