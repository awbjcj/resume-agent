import { useState } from "react";
import { Loader2, Mail, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  useEmailDrafts,
  useGenerateEmailDraft,
  useSaveEmailDraft,
} from "./use-email-drafts";

const TYPES = [
  { value: "follow_up", label: "Follow-up" },
  { value: "thank_you", label: "Thank you" },
  { value: "withdrawal", label: "Withdrawal" },
  { value: "cold_outreach", label: "Cold outreach" },
] as const;

export function EmailDraftDialog({
  jobId,
  defaultType = "follow_up",
  open,
  onOpenChange,
}: {
  jobId: number;
  defaultType?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [draftType, setDraftType] = useState(defaultType);
  const [instructions, setInstructions] = useState("");
  const { data: drafts = [] } = useEmailDrafts(jobId, open);
  const generate = useGenerateEmailDraft(jobId);
  const save = useSaveEmailDraft(jobId);
  const latest = drafts[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="size-4" aria-hidden="true" /> Draft email
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          {TYPES.map((t) => (
            <Button
              key={t.value}
              size="sm"
              variant={draftType === t.value ? "default" : "outline"}
              aria-pressed={draftType === t.value}
              onClick={() => setDraftType(t.value)}
            >
              {t.label}
            </Button>
          ))}
        </div>
        <Textarea
          rows={2}
          aria-label="Optional instructions"
          placeholder="Optional instructions (e.g. mention the take-home score)"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <Button
          disabled={generate.isPending}
          onClick={() =>
            generate.mutate({
              draftType,
              instructions: instructions || undefined,
            })
          }
        >
          {generate.isPending && (
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          )}
          Generate draft
        </Button>
        {latest && (
          <div className="space-y-2 rounded-lg border p-3 text-sm">
            <div className="text-xs text-muted-foreground">
              To: {latest.toAddr || "(fill in Gmail)"}
            </div>
            <div className="font-medium">{latest.subject}</div>
            <p className="whitespace-pre-wrap text-sm">{latest.body}</p>
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigator.clipboard.writeText(latest.body)}
              >
                Copy body
              </Button>
              <Button
                size="sm"
                disabled={save.isPending || latest.state === "saved"}
                onClick={() => latest.id && save.mutate(latest.id)}
              >
                <Save className="size-4" aria-hidden="true" />
                {latest.state === "saved"
                  ? "Saved to Gmail"
                  : "Save to Gmail drafts"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
