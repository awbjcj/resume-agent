import { useId, useState } from "react";
import { Download, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, openDownload, unwrap } from "@/lib/api/client";

const SCOPES = [
  {
    value: "jobs",
    label: "Jobs",
    description:
      "Pulled jobs, applications, tailored resumes, cover letters, rendered files, and run history.",
  },
  {
    value: "profile",
    label: "Profile",
    description:
      "Profile sources, extracted facts, skill matrix, fragments, and documents. Hand-written overrides stay.",
  },
  {
    value: "all",
    label: "Everything",
    description:
      "Jobs and profile plus discovery caches. Configuration and API keys stay.",
  },
] as const;

type Scope = (typeof SCOPES)[number]["value"];

export function DangerZoneCard({
  reloadPage = () => window.location.reload(),
}: {
  reloadPage?: () => void;
}) {
  const confirmId = useId();
  const [scope, setScope] = useState<Scope>("jobs");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [resetting, setResetting] = useState(false);
  const selected = SCOPES.find((option) => option.value === scope) ?? SCOPES[0];

  function selectScope(values: string[]) {
    const next = values.at(-1) as Scope | undefined;
    if (!next) return;
    setScope(next);
    setConfirmText("");
  }

  function setOpen(open: boolean) {
    setDialogOpen(open);
    if (!open) {
      setConfirmText("");
      setResetting(false);
    }
  }

  async function runReset() {
    if (confirmText !== "RESET" || resetting) return;
    setResetting(true);
    try {
      const report = await unwrap(
        api.POST("/api/account/reset", {
          params: { query: { confirm: "RESET" } },
          body: { scope },
        }),
      );
      const failureCount = Object.keys(report.failures).length;
      if (failureCount > 0) {
        toast.warning(
          `Reset finished with ${failureCount} file(s) left behind; run it again to finish.`,
        );
        setResetting(false);
        return;
      }
      reloadPage();
    } catch (error) {
      toast.error((error as Error).message);
      setResetting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Danger zone</CardTitle>
        <CardDescription>
          Clear this workspace&apos;s data. Configuration, API keys, and
          hand-written profile overrides are always kept.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FieldSet>
          <FieldLegend variant="label">What to clear</FieldLegend>
          <FieldDescription>
            Existing job artifacts remain when only the profile is reset.
          </FieldDescription>
          <ToggleGroup
            aria-label="Reset scope"
            value={[scope]}
            onValueChange={selectScope}
          >
            {SCOPES.map((option) => (
              <ToggleGroupItem
                key={option.value}
                value={option.value}
                aria-label={`${option.label}: ${option.description}`}
                className="h-auto min-w-48 flex-1 items-start justify-start text-left whitespace-normal"
              >
                <span className="flex flex-col gap-1">
                  <span>{option.label}</span>
                  <span className="text-muted-foreground">
                    {option.description}
                  </span>
                </span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </FieldSet>
      </CardContent>
      <CardFooter>
        <AlertDialog open={dialogOpen} onOpenChange={setOpen}>
          <AlertDialogTrigger render={<Button variant="destructive" />}>
            <TriangleAlert data-icon="inline-start" />
            Reset data
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                Reset {selected.label.toLowerCase()}?
              </AlertDialogTitle>
              <AlertDialogDescription>
                This permanently deletes {selected.description.toLowerCase()} Type
                RESET to continue.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <FieldGroup>
              <Button
                variant="outline"
                onClick={() => void openDownload("/api/account/export")}
              >
                <Download data-icon="inline-start" />
                Export backup first
              </Button>
              <Field>
                <FieldLabel htmlFor={confirmId}>Type RESET to confirm</FieldLabel>
                <Input
                  id={confirmId}
                  value={confirmText}
                  autoComplete="off"
                  onChange={(event) => setConfirmText(event.target.value)}
                />
              </Field>
            </FieldGroup>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={resetting}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                disabled={confirmText !== "RESET" || resetting}
                onClick={(event) => {
                  event.preventDefault();
                  void runReset();
                }}
              >
                {resetting ? <Spinner data-icon="inline-start" /> : null}
                Erase selected data
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardFooter>
    </Card>
  );
}
