import { useState } from "react";
import { CircleAlert, LockKeyhole } from "lucide-react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

import { ResetSectionButton } from "../ResetSectionButton";
import {
  type AgentPromptItem,
  usePrompts,
  useSaveGuidance,
} from "../use-prompts";

const STAGES = [
  ["tailoring", "Tailoring"],
  ["review", "Review"],
  ["cover-letter", "Cover letters"],
  ["discovery", "Discovery"],
  ["profile", "Profile"],
  ["interview", "Interview"],
  ["email", "Email"],
] as const;

function PromptRow({ item }: { item: AgentPromptItem }) {
  const save = useSaveGuidance();
  const [guidance, setGuidance] = useState(item.guidance ?? "");

  const guidanceId = `guidance-${item.key}`;
  return (
    <AccordionItem value={item.key}>
      <AccordionTrigger>
        <span className="flex min-w-0 flex-col gap-0.5 pr-3">
          <span>{item.title}</span>
          <span className="text-xs font-normal text-muted-foreground">
            {item.description}
          </span>
        </span>
      </AccordionTrigger>
      <AccordionContent className="flex flex-col gap-4">
        <div className="rounded-lg bg-muted/45 p-4 ring-1 ring-foreground/8">
          <ol className="flex list-decimal flex-col gap-2 pl-5 font-mono text-xs leading-relaxed text-muted-foreground">
            {item.instructions.map((instruction, index) => (
              <li key={`${item.key}-${index}`}>{instruction}</li>
            ))}
          </ol>
        </div>
        {item.editable ? (
          <Field>
            <FieldLabel htmlFor={guidanceId}>Your guidance for {item.title}</FieldLabel>
            <Textarea
              id={guidanceId}
              maxLength={4000}
              rows={4}
              value={guidance}
              onChange={(event) => setGuidance(event.target.value)}
              placeholder="Steer tone, emphasis, or process without changing facts."
            />
            <div className="flex items-center justify-between gap-3">
              <FieldDescription>{guidance.length.toLocaleString()} / 4,000</FieldDescription>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!item.guidance || save.isPending}
                  onClick={() => save.mutate({ key: item.key, guidance: "" })}
                >
                  Reset this agent
                </Button>
                <Button
                  size="sm"
                  disabled={save.isPending || guidance === (item.guidance ?? "")}
                  onClick={() => save.mutate({ key: item.key, guidance })}
                >
                  {save.isPending ? <Spinner data-icon="inline-start" /> : null}
                  Save guidance
                </Button>
              </div>
            </div>
          </Field>
        ) : (
          <Badge variant="secondary" className="w-fit">
            <LockKeyhole data-icon="inline-start" aria-hidden="true" />
            Integrity gate — read-only
          </Badge>
        )}
      </AccordionContent>
    </AccordionItem>
  );
}

export function AgentPromptsPage() {
  const prompts = usePrompts();

  if (prompts.isPending) {
    return <Skeleton className="h-80 w-full" aria-label="Loading agent prompts" />;
  }
  if (prompts.isError) {
    return (
      <Alert variant="destructive">
        <CircleAlert aria-hidden="true" />
        <AlertTitle>Couldn&apos;t load agent prompts</AlertTitle>
        <AlertDescription>{prompts.error.message}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Agent prompts</h1>
          <p className="text-sm text-muted-foreground">
            Read every built-in prompt and add subordinate guidance. Guidance can
            steer tone, emphasis, and process, never facts or integrity rules.
          </p>
        </div>
        <ResetSectionButton sectionId="agent_guidance" label="Agent prompts" />
      </header>
      {STAGES.map(([stage, label]) => {
        const items = prompts.data.filter((item) => item.stage === stage);
        if (items.length === 0) return null;
        return (
          <section key={stage} aria-labelledby={`${stage}-heading`}>
            <h2 id={`${stage}-heading`} className="text-base font-semibold">
              {label}
            </h2>
            <Accordion multiple className="mt-2 rounded-lg border px-3">
              {items.map((item) => (
                <PromptRow
                  key={`${item.key}:${item.guidance ?? ""}`}
                  item={item}
                />
              ))}
            </Accordion>
          </section>
        );
      })}
    </div>
  );
}
