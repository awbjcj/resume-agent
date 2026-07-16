import { useId, useState } from "react";
import { ExternalLink, Link, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useAddUrl, useSyncGithub } from "@/features/profile-sources/use-sources";

import type { CoachResearchAction } from "./use-coach";

export function ResearchActionCard({ action }: { action: CoachResearchAction }) {
  const fieldId = useId();
  const syncGithub = useSyncGithub();
  const addUrl = useAddUrl();
  const [url, setUrl] = useState(/^https?:\/\//i.test(action.target) ? action.target : "");

  if (action.kind === "harvest_repo") {
    return (
      <Card size="sm" className="border-dashed bg-muted/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <RefreshCw className="size-4 text-primary" aria-hidden="true" />
            Refresh repository evidence
          </CardTitle>
          <CardDescription>{action.why}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{action.target}</span>
          <Button
            size="sm"
            variant="outline"
            disabled={syncGithub.isPending}
            onClick={() => syncGithub.mutate()}
          >
            {syncGithub.isPending ? <Spinner data-icon="inline-start" /> : null}
            Re-harvest
          </Button>
        </CardContent>
      </Card>
    );
  }

  const validUrl = /^https?:\/\/[^\s]+$/i.test(url);
  return (
    <Card size="sm" className="border-dashed bg-muted/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <ExternalLink className="size-4 text-primary" aria-hidden="true" />
          Add supporting page
        </CardTitle>
        <CardDescription>{action.why}</CardDescription>
      </CardHeader>
      <CardContent>
        <Field>
          <FieldLabel htmlFor={fieldId}>{action.target}</FieldLabel>
          <FieldDescription>Use a public portfolio, case study, or project URL.</FieldDescription>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Link className="absolute left-3 top-2.5 size-4 text-muted-foreground" aria-hidden="true" />
              <Input
                id={fieldId}
                className="pl-9"
                type="url"
                value={url}
                placeholder="https://example.com/project"
                onChange={(event) => setUrl(event.target.value)}
              />
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={!validUrl || addUrl.isPending}
              onClick={() => void addUrl.mutateAsync({ url })}
            >
              {addUrl.isPending ? <Spinner data-icon="inline-start" /> : null}
              Add page
            </Button>
          </div>
        </Field>
      </CardContent>
    </Card>
  );
}
