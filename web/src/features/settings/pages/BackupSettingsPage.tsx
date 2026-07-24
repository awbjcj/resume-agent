import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Archive, Download } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { apiUrl, authHeaders, openDownload } from "@/lib/api/client";

import { ResetSectionButton } from "../ResetSectionButton";
import {
  type SettingsSection,
  useSettingsSections,
} from "../use-settings-sections";

type Preview = {
  sections: SettingsSection[];
  unknownSections: string[];
};

async function post(path: string, file: File): Promise<unknown> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body?.error?.message ?? "Request failed");
  }
  return body;
}

/** Canonical, complete surface for the settings registry: profile_sources
 *  and the three correction ledgers have no dedicated Settings page, so this
 *  table -- not the per-page shortcut buttons in Task 10 -- is what makes
 *  every customizable section transferable and resettable. */
export function BackupSettingsPage() {
  const fileId = useId();
  const queryClient = useQueryClient();
  const { data: sections = [], isLoading } = useSettingsSections();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const previewRequest = useRef(0);

  async function choose(chosen: File | null) {
    const request = ++previewRequest.current;
    setFile(chosen);
    setPreview(null);
    if (!chosen) return;
    setBusy(true);
    try {
      const next = (await post("/api/settings/bundle/preview", chosen)) as Preview;
      if (request === previewRequest.current) setPreview(next);
    } catch (error) {
      if (request === previewRequest.current) {
        toast.error((error as Error).message);
      }
    } finally {
      if (request === previewRequest.current) setBusy(false);
    }
  }

  async function apply() {
    if (!file) return;
    setBusy(true);
    try {
      await post("/api/settings/bundle?confirm=APPLY", file);
      toast.success("Settings bundle applied");
      setFile(null);
      setPreview(null);
      await queryClient.invalidateQueries();
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="border-b">
          <CardTitle>
            <h3>Settings bundle</h3>
          </CardTitle>
          <CardDescription>
            Move your customizations between installs. A bundle carries only the
            settings below — never your jobs, your profile, or your API keys.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              onClick={() => void openDownload("/api/settings/bundle")}
            >
              <Download data-icon="inline-start" />
              Export settings
            </Button>
          </div>
          <Field>
            <FieldLabel htmlFor={fileId}>Bundle file</FieldLabel>
            <Input
              id={fileId}
              type="file"
              accept=".tar.gz,.tgz,application/gzip"
              onChange={(event) => void choose(event.target.files?.[0] ?? null)}
            />
          </Field>
          {preview ? (
            <div className="rounded-lg border p-4 text-sm">
              <p>
                <strong>This bundle will replace:</strong>{" "}
                {preview.sections.map((section) => section.label).join(", ") ||
                  "nothing"}
                . Your other settings are untouched.
              </p>
              {preview.unknownSections.length > 0 ? (
                <p className="mt-2 text-muted-foreground">
                  Ignoring {preview.unknownSections.length} section(s) this
                  version does not recognize.
                </p>
              ) : null}
              <Button
                className="mt-3"
                disabled={busy || preview.sections.length === 0}
                onClick={() => void apply()}
              >
                {busy ? <Spinner data-icon="inline-start" /> : null}
                Apply bundle
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
              <Archive aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <CardTitle>
                <h3>Customizable settings</h3>
              </CardTitle>
              <CardDescription>
                Everything a bundle can carry, and everything you can reset.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col divide-y">
          {isLoading ? <Spinner /> : null}
          {sections.map((section) => (
            <div
              key={section.id}
              className="flex flex-wrap items-center gap-3 py-3"
            >
              <span className="font-medium">{section.label}</span>
              <Badge variant={section.customized ? "default" : "outline"}>
                {section.customized ? "Customized" : "Default"}
              </Badge>
              <div className="ml-auto">
                <ResetSectionButton
                  sectionId={section.id}
                  label={section.label}
                  note={
                    section.id === "skill_overrides"
                      ? "Takes effect on your next profile build."
                      : undefined
                  }
                />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
