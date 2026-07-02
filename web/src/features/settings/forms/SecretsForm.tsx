import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { SecretsPatch, SecretStatus } from "../use-secrets";

export const SECRET_LABELS: Record<string, string> = {
  anthropicApiKey: "Anthropic API key",
  openaiApiKey: "OpenAI API key",
  geminiApiKey: "Gemini API key",
  deepseekApiKey: "DeepSeek API key",
  githubToken: "GitHub token",
  adzunaAppId: "Adzuna app ID",
  adzunaAppKey: "Adzuna app key",
  linkedinEmail: "LinkedIn email",
  linkedinPassword: "LinkedIn password",
};

export function SecretsForm({
  statuses, saving, onSave,
}: {
  statuses: SecretStatus[]; saving: boolean; onSave: (patch: SecretsPatch) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const startEdit = (key: string) => {
    setEditing(key);
    setDraft("");
  };

  return (
    <FieldGroup>
      {statuses.map((s) => {
        const label = SECRET_LABELS[s.key] ?? s.key;
        return (
          <Field key={s.key}>
            <div className="flex flex-wrap items-center gap-3">
              <FieldLabel className="min-w-44">{label}</FieldLabel>
              {s.isSet ? (
                <Badge variant="secondary">Set{s.hint ? ` · ••••${s.hint}` : ""}</Badge>
              ) : (
                <Badge variant="outline">Not set</Badge>
              )}
              <div className="ml-auto flex gap-2">
                {editing !== s.key && (
                  <Button variant="outline" size="sm" onClick={() => startEdit(s.key)}>
                    {s.isSet ? `Replace ${label}` : `Add ${label}`}
                  </Button>
                )}
                {s.isSet && (
                  <Button variant="outline" size="sm" disabled={saving}
                    aria-label={`Clear ${label}`}
                    onClick={() => onSave({ [s.key]: null })}>
                    Clear {label}
                  </Button>
                )}
              </div>
            </div>
            {editing === s.key && (
              <div className="mt-2 flex gap-2">
                <Input
                  type="password"
                  aria-label={`${label} new value`}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  autoComplete="off"
                />
                <Button disabled={saving || draft === ""}
                  onClick={() => { onSave({ [s.key]: draft }); setEditing(null); }}>
                  Save key
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            )}
          </Field>
        );
      })}
    </FieldGroup>
  );
}
