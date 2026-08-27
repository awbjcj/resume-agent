import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSeparator } from "@/components/ui/field";
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
  googleOauthClientId: "Google OAuth client ID",
  googleOauthClientSecret: "Google OAuth client secret",
};

// Extra context shown under fields whose purpose isn't obvious from the label alone.
const SECRET_DESCRIPTIONS: Record<string, string> = {
  googleOauthClientId:
    "Overrides the platform Gmail sign-in client for your workspace only. Must be a Web application OAuth client, not a Desktop app client.",
  googleOauthClientSecret:
    "Paired secret for the client ID above — both must be set together.",
};

// The client ID is meant to be public (it's sent to Google in the browser), so
// it doesn't need to be masked like a real secret while being typed or pasted.
const SECRET_PLAIN_TEXT_KEYS = new Set(["googleOauthClientId"]);

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
        const description = SECRET_DESCRIPTIONS[s.key];
        return (
          <div key={s.key} className="flex flex-col gap-4">
            {s.key === "googleOauthClientId" && (
              <FieldSeparator>Gmail OAuth client (optional)</FieldSeparator>
            )}
            <Field>
              <div className="flex flex-wrap items-center gap-3">
                <FieldLabel className="min-w-0 sm:min-w-44">{label}</FieldLabel>
                {s.isSet ? (
                  <Badge variant="secondary">Set{s.hint ? ` · ••••${s.hint}` : ""}</Badge>
                ) : (
                  <Badge variant="outline">Not set</Badge>
                )}
                <div className="flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">
                  {editing !== s.key && (
                    <Button className="min-w-0 flex-1 sm:flex-none" variant="outline" size="sm" onClick={() => startEdit(s.key)}>
                      {s.isSet ? `Replace ${label}` : `Add ${label}`}
                    </Button>
                  )}
                  {s.isSet && (
                    <Button className="min-w-0 flex-1 sm:flex-none" variant="outline" size="sm" disabled={saving}
                      aria-label={`Clear ${label}`}
                      onClick={() => onSave({ [s.key]: null })}>
                      Clear {label}
                    </Button>
                  )}
                </div>
              </div>
              {description && <FieldDescription>{description}</FieldDescription>}
              {editing === s.key && (
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  <Input
                    type={SECRET_PLAIN_TEXT_KEYS.has(s.key) ? "text" : "password"}
                    aria-label={`${label} new value`}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    autoComplete="off"
                  />
                  <Button className="w-full sm:w-auto" disabled={saving || draft === ""}
                    onClick={() => { onSave({ [s.key]: draft }); setEditing(null); }}>
                    Save key
                  </Button>
                  <Button className="w-full sm:w-auto" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                </div>
              )}
            </Field>
          </div>
        );
      })}
    </FieldGroup>
  );
}
