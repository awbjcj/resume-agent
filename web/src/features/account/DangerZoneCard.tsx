import { useId, useRef, useState } from "react";
import {
  BriefcaseBusiness,
  ContactRound,
  Download,
  Layers3,
  LockKeyhole,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
    icon: BriefcaseBusiness,
    description:
      "Pulled jobs, applications, tailored resumes, cover letters, rendered files, and run history.",
  },
  {
    value: "profile",
    label: "Profile",
    icon: ContactRound,
    description:
      "Extracted facts, skill matrix, and fragments. Source documents and hand-written overrides stay.",
  },
  {
    value: "all",
    label: "Everything",
    icon: Layers3,
    description:
      "Jobs and derived profile data plus discovery caches. Sources, configuration, and API keys stay.",
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
  const resettingRef = useRef(false);
  const selected = SCOPES.find((option) => option.value === scope) ?? SCOPES[0];

  function selectScope(values: string[]) {
    const next = values.at(-1) as Scope | undefined;
    if (!next) return;
    setScope(next);
    setConfirmText("");
  }

  function setOpen(open: boolean, eventDetails: { cancel(): void }) {
    if (!open && resettingRef.current) {
      eventDetails.cancel();
      return;
    }
    setDialogOpen(open);
    if (!open) {
      setConfirmText("");
      setResetting(false);
    }
  }

  async function runReset() {
    if (confirmText !== "RESET" || resetting) return;
    resettingRef.current = true;
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
        resettingRef.current = false;
        setResetting(false);
        return;
      }
      reloadPage();
      resettingRef.current = false;
      setResetting(false);
    } catch (error) {
      toast.error((error as Error).message);
      resettingRef.current = false;
      setResetting(false);
    }
  }

  return (
    <Card className="bg-destructive/5 ring-destructive/30">
      <CardHeader className="border-b">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-destructive/10 text-destructive">
              <ShieldAlert aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <CardTitle>Danger zone</CardTitle>
              <CardDescription>
                Clear this workspace&apos;s data. Configuration, API keys, and
                sources are kept until you reset them explicitly. Hand-written
                profile overrides are always kept.
              </CardDescription>
            </div>
          </div>
          <Badge variant="destructive" className="shrink-0 self-start">
            Irreversible
          </Badge>
        </div>
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
            className="grid auto-rows-fr grid-cols-1 items-stretch gap-2 md:grid-cols-3"
          >
            {SCOPES.map((option) => {
              const ScopeIcon = option.icon;
              return (
                <ToggleGroupItem
                  key={option.value}
                  value={option.value}
                  aria-label={`${option.label}: ${option.description}`}
                  className="h-full min-w-0 items-stretch justify-start rounded-lg p-0 text-left whitespace-normal"
                >
                  <span className="flex h-full flex-1 flex-col gap-2 p-3">
                    <span className="flex items-center gap-2 font-medium">
                      <ScopeIcon aria-hidden="true" />
                      {option.label}
                      {option.value === "jobs" ? (
                        <Badge variant="outline" className="ml-auto">
                          Common
                        </Badge>
                      ) : null}
                    </span>
                    <span className="text-xs leading-relaxed text-muted-foreground">
                      {option.description}
                    </span>
                  </span>
                </ToggleGroupItem>
              );
            })}
          </ToggleGroup>
        </FieldSet>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3 bg-transparent sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <LockKeyhole aria-hidden="true" className="size-4" />
          A typed confirmation is required before anything is erased.
        </div>
        <AlertDialog open={dialogOpen} onOpenChange={setOpen}>
          <AlertDialogTrigger render={<Button variant="destructive" />}>
            <TriangleAlert data-icon="inline-start" />
            Reset data
          </AlertDialogTrigger>
          <AlertDialogContent className="sm:max-w-md">
            <AlertDialogHeader>
              <AlertDialogMedia className="bg-destructive/10 text-destructive">
                <TriangleAlert aria-hidden="true" />
              </AlertDialogMedia>
              <AlertDialogTitle>
                Reset {selected.label.toLowerCase()}?
              </AlertDialogTitle>
              <AlertDialogDescription>
                This permanently deletes {selected.description.toLowerCase()} Type
                RESET to continue.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <FieldGroup>
              <Alert>
                <ShieldCheck aria-hidden="true" />
                <AlertTitle>Protected settings stay in place</AlertTitle>
                <AlertDescription>
                  Configuration, API keys, and hand-written profile overrides
                  will not be removed.
                </AlertDescription>
              </Alert>
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
                  placeholder="RESET"
                  autoComplete="off"
                  onChange={(event) => setConfirmText(event.target.value)}
                />
              </Field>
            </FieldGroup>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={resetting}>Cancel</AlertDialogCancel>
              <Button
                variant="destructive"
                disabled={confirmText !== "RESET" || resetting}
                onClick={() => void runReset()}
              >
                {resetting ? <Spinner data-icon="inline-start" /> : null}
                Erase selected data
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardFooter>
    </Card>
  );
}
