import { useState } from "react";
import { Link, StickyNote } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

import { useAddNote, useAddUrl } from "./use-sources";

export function MaterialIntakeDialogs() {
  const addNote = useAddNote();
  const addUrl = useAddUrl();
  const [noteOpen, setNoteOpen] = useState(false);
  const [urlOpen, setUrlOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");

  return (
    <>
      <Dialog open={noteOpen} onOpenChange={setNoteOpen}>
        <DialogTrigger render={<Button variant="outline" />}>
          <StickyNote data-icon="inline-start" aria-hidden="true" />
          Add note
        </DialogTrigger>
        <DialogContent>
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              addNote.mutate(
                { title: title.trim(), text: text.trim() },
                {
                  onSuccess: () => {
                    setTitle("");
                    setText("");
                    setNoteOpen(false);
                  },
                },
              );
            }}
          >
            <DialogHeader>
              <DialogTitle>Add a note</DialogTitle>
              <DialogDescription>
                Add first-hand context that is missing from your uploaded files.
              </DialogDescription>
            </DialogHeader>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="profile-note-title">Note title</FieldLabel>
                <Input
                  id="profile-note-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="profile-note-text">Note text</FieldLabel>
                <Textarea
                  id="profile-note-text"
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  required
                />
              </Field>
            </FieldGroup>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button type="submit" disabled={addNote.isPending || !title.trim() || !text.trim()}>
                {addNote.isPending ? <Spinner data-icon="inline-start" /> : null}
                Save note
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={urlOpen} onOpenChange={setUrlOpen}>
        <DialogTrigger render={<Button variant="outline" />}>
          <Link data-icon="inline-start" aria-hidden="true" />
          Add URL
        </DialogTrigger>
        <DialogContent>
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              addUrl.mutate(
                { url: url.trim() },
                {
                  onSuccess: () => {
                    setUrl("");
                    setUrlOpen(false);
                  },
                },
              );
            }}
          >
            <DialogHeader>
              <DialogTitle>Add a public page</DialogTitle>
              <DialogDescription>
                Import text from a public HTTP or HTTPS page as profile evidence.
              </DialogDescription>
            </DialogHeader>
            <Field>
              <FieldLabel htmlFor="profile-public-url">Public URL</FieldLabel>
              <Input
                id="profile-public-url"
                type="url"
                placeholder="https://example.com/work"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                required
              />
            </Field>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button type="submit" disabled={addUrl.isPending || !url.trim()}>
                {addUrl.isPending ? <Spinner data-icon="inline-start" /> : null}
                Ingest page
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
