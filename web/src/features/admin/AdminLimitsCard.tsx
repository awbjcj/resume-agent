import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, ShieldCheck } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";

type SystemDefaults = {
  maxActiveJobs: number;
  maxConcurrentRuns: number;
};

const LIMIT_FIELDS = [
  {
    key: "maxActiveJobs",
    label: "Active jobs",
    description: "Unarchived jobs per workspace",
  },
  {
    key: "maxConcurrentRuns",
    label: "Concurrent runs",
    description: "Simultaneous background runs",
  },
] as const;

export function AdminLimitsCard() {
  const queryClient = useQueryClient();
  const defaults = useQuery({
    queryKey: ["admin", "defaults"],
    queryFn: () => unwrap(api.GET("/api/admin/system/defaults")),
  });
  const [draft, setDraft] = useState<SystemDefaults | null>(null);
  const saveDefaults = useMutation({
    mutationFn: (body: SystemDefaults) =>
      unwrap(api.PUT("/api/admin/system/defaults", { body })),
    onSuccess: (result) => {
      setDraft(result);
      void queryClient.invalidateQueries({ queryKey: ["admin", "defaults"] });
    },
  });

  if (defaults.isPending) return <Skeleton className="h-72 w-full" />;
  if (defaults.isError || !defaults.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Member defaults are unavailable</AlertTitle>
        <AlertDescription>{defaults.error?.message ?? "Please try again."}</AlertDescription>
      </Alert>
    );
  }
  const limits = draft ?? defaults.data;

  return (
    <Card className="h-full">
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <Gauge aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle>
              <h3>Member defaults</h3>
            </CardTitle>
            <CardDescription>
              Non-financial workspace limits. Cost allowances are managed in Cost quotas.
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge variant="secondary">0 = unlimited</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <FieldGroup className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {LIMIT_FIELDS.map((field) => (
            <Field key={field.key}>
              <FieldLabel htmlFor={field.key}>{field.label}</FieldLabel>
              <Input
                id={field.key}
                type="number"
                min={0}
                value={limits[field.key]}
                onChange={(event) =>
                  setDraft({ ...limits, [field.key]: Number(event.target.value) })
                }
              />
              <FieldDescription>{field.description}</FieldDescription>
            </Field>
          ))}
        </FieldGroup>
        {saveDefaults.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Defaults could not be saved</AlertTitle>
            <AlertDescription>{saveDefaults.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
      <CardFooter className="justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Administrator accounts always remain unlimited.
        </p>
        <Button onClick={() => saveDefaults.mutate(limits)} disabled={saveDefaults.isPending}>
          {saveDefaults.isPending ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <ShieldCheck data-icon="inline-start" />
          )}
          Save defaults
        </Button>
      </CardFooter>
    </Card>
  );
}
