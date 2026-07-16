import { useState } from "react";
import { FileCheck2, PencilLine, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

import type { CoachDraftNote } from "./use-coach";

interface DraftNoteCardProps {
  note: CoachDraftNote;
  saving: boolean;
  discarding: boolean;
  onSave: (note: CoachDraftNote) => void;
  onDiscard: () => void;
}

export function DraftNoteCard({ note, saving, discarding, onSave, onDiscard }: DraftNoteCardProps) {
  const [editing, setEditing] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [title, setTitle] = useState(note.title);
  const [summary, setSummary] = useState(note.summary);
  const pending = note.status === "pending";

  return (
    <Card className="border-primary/25 bg-primary/[0.035] shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileCheck2 className="size-4 text-primary" aria-hidden="true" />
          {editing ? "Edit profile note" : title}
        </CardTitle>
        <CardDescription>
          {pending ? "Review this grounded note before adding it to your profile." : `Note ${note.status}.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {editing ? (
          <>
            <Field>
              <FieldLabel htmlFor={`draft-title-${note.topicId}`}>Title</FieldLabel>
              <Input id={`draft-title-${note.topicId}`} value={title} onChange={(event) => setTitle(event.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor={`draft-summary-${note.topicId}`}>Summary</FieldLabel>
              <Textarea id={`draft-summary-${note.topicId}`} rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} />
              <FieldDescription>Keep the claim specific and supported by your words below.</FieldDescription>
            </Field>
          </>
        ) : (
          <p className="text-base leading-7">{summary}</p>
        )}
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Your evidence</div>
          {(note.quotes ?? []).map((quote) => (
            <blockquote key={quote} className="border-l-2 border-primary/35 pl-4 text-base italic leading-7 text-muted-foreground">
              “{quote}”
            </blockquote>
          ))}
        </div>
      </CardContent>
      {pending ? (
        <CardFooter className="flex flex-wrap gap-2 border-t bg-muted/20">
          {confirmDiscard ? (
            <>
              <span className="mr-auto text-sm text-muted-foreground">Discard this draft permanently?</span>
              <Button size="sm" variant="outline" onClick={() => setConfirmDiscard(false)}>Keep</Button>
              <Button size="sm" variant="destructive" disabled={discarding} onClick={onDiscard}>
                {discarding ? <Spinner data-icon="inline-start" /> : <Trash2 aria-hidden="true" />}
                Discard
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                disabled={saving || !title.trim() || !summary.trim() || !(note.quotes ?? []).length}
                onClick={() => onSave({ ...note, title: title.trim(), summary: summary.trim() })}
              >
                {saving ? <Spinner data-icon="inline-start" /> : <Save aria-hidden="true" />}
                Save note
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing((value) => !value)}>
                <PencilLine aria-hidden="true" />
                {editing ? "Preview" : "Edit"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDiscard(true)}>
                <Trash2 aria-hidden="true" />
                Discard
              </Button>
            </>
          )}
        </CardFooter>
      ) : (
        <CardFooter className="border-t bg-muted/20"><Badge variant="secondary">{note.status}</Badge></CardFooter>
      )}
    </Card>
  );
}
