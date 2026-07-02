import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { DocumentManager } from "@/features/settings/forms/DocumentManager";
import { useConfig, useSaveConfig } from "@/features/settings/use-config";
import { useDraft } from "@/features/settings/use-draft";
import type { paths } from "@/lib/api/schema";

type ProfileDoc = paths["/api/config/profile"]["get"]["responses"][200]["content"]["application/json"];

export function DocumentsStep() {
  const { data } = useConfig("/api/config/profile");
  const save = useSaveConfig("/api/config/profile");
  const { draft, setDraft } = useDraft(data as ProfileDoc | undefined);
  const navigate = useNavigate();

  const continueToNext = () => {
    if (draft) save.mutate(draft);
    navigate("/setup/search");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Documents</CardTitle>
        <CardDescription>Upload a resume — this is what the profile is built from.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <DocumentManager />
        {draft && (
          <Field>
            <FieldLabel htmlFor="wizard-github">GitHub username</FieldLabel>
            <Input id="wizard-github" value={draft.githubUsername ?? ""}
              onChange={(e) => setDraft({ ...draft, githubUsername: e.target.value || null })} />
          </Field>
        )}
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate("/setup/search")}>Skip for now</Button>
        <Button onClick={continueToNext}>Save & continue</Button>
      </CardFooter>
    </Card>
  );
}
