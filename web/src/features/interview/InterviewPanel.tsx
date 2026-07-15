import { useState } from "react";
import { Bot, Link, RefreshCw, Send, Sparkles } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useAddUrl, useSyncGithub } from "@/features/profile-sources/use-sources";

import {
  type InterviewRound,
  useInterviewHistory,
  useInterviewRound,
  useStartInterview,
  useSubmitInterview,
} from "./use-interview";

type ResearchAction = InterviewRound["researchActions"][number];

function AssistantMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex max-w-[90%] items-start gap-2 sm:max-w-[82%]">
      <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Bot className="size-4" aria-hidden="true" />
      </div>
      <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3 text-sm leading-relaxed">
        {children}
      </div>
    </div>
  );
}

function AnswerMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="ml-auto max-w-[90%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm leading-relaxed text-primary-foreground sm:max-w-[82%]">
      {children}
    </div>
  );
}

function ResearchActionControl({ action }: { action: ResearchAction }) {
  const syncGithub = useSyncGithub();
  const addUrl = useAddUrl();
  const initialUrl = /^https?:\/\//i.test(action.target) ? action.target : "";
  const [url, setUrl] = useState(initialUrl);

  if (action.kind === "harvest_repo") {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3">
        <RefreshCw className="size-4 text-muted-foreground" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{action.target}</div>
          <div className="text-xs text-muted-foreground">{action.why}</div>
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={syncGithub.isPending}
          onClick={() => syncGithub.mutate()}
        >
          {syncGithub.isPending ? <Spinner data-icon="inline-start" /> : null}
          Re-harvest repo
        </Button>
      </div>
    );
  }

  const validUrl = /^https?:\/\/[^\s]+$/i.test(url);
  return (
    <Field className="rounded-lg border bg-card p-3">
      <FieldLabel htmlFor={`interview-url-${action.target}`}>URL for {action.target}</FieldLabel>
      <FieldDescription>{action.why}</FieldDescription>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Link className="absolute top-2.5 left-3 size-4 text-muted-foreground" aria-hidden="true" />
          <Input
            id={`interview-url-${action.target}`}
            className="pl-9"
            type="url"
            value={url}
            placeholder="https://portfolio.example/project"
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
  );
}

export function InterviewPanel() {
  const history = useInterviewHistory();
  const start = useStartInterview();
  const submit = useSubmitInterview();
  const [runId, setRunId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const current = useInterviewRound(runId);

  const startRound = async () => {
    const run = await start.mutateAsync();
    setAnswers({});
    setRunId(run.runId);
  };

  const sendAnswers = async () => {
    if (!runId || !current.round) return;
    await submit.mutateAsync({
      runId,
      answers: current.round.questions.map((question) => ({
        questionId: question.id,
        text: answers[question.id] ?? "",
      })),
      build: true,
    });
    setAnswers({});
    setRunId(null);
  };

  return (
    <Card className="bg-gradient-to-br from-card via-card to-primary/[0.035]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" aria-hidden="true" />
          Profile interview
        </CardTitle>
        <CardDescription>
          Turn missing outcomes and project evidence into grounded profile notes.
        </CardDescription>
        <CardAction>
          <Button
            size="sm"
            disabled={start.isPending || current.state === "running"}
            onClick={() => void startRound()}
          >
            {start.isPending || current.state === "running" ? (
              <Spinner data-icon="inline-start" />
            ) : null}
            {current.state === "running" ? "Reviewing profile…" : "Start interview"}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {(history.data?.rounds ?? []).map((round) => (
          <div className="flex flex-col gap-2" key={round.roundId}>
            {(round.questions ?? []).map((question) => {
              const answer = (round.answers ?? []).find(
                (candidate) => candidate.questionId === question.id,
              );
              return (
                <div className="contents" key={question.id}>
                  <AssistantMessage>
                    {question.gap ? (
                      <Badge className="mb-2" variant="outline">{question.gap}</Badge>
                    ) : null}
                    <div>{question.questionText}</div>
                  </AssistantMessage>
                  {answer ? <AnswerMessage>{answer.answerText}</AnswerMessage> : null}
                </div>
              );
            })}
          </div>
        ))}

        {current.state === "error" ? (
          <Alert variant="destructive">
            <AlertTitle>Interview could not finish</AlertTitle>
            <AlertDescription>{current.error}</AlertDescription>
          </Alert>
        ) : null}

        {current.round ? (
          <div className="flex flex-col gap-4 border-t pt-4">
            {current.round.questions.map((question) => (
              <div className="flex flex-col gap-2" key={question.id}>
                <AssistantMessage>
                  <Badge className="mb-2" variant="outline">{question.gap}</Badge>
                  <div>{question.questionText}</div>
                  {question.whyItMatters ? (
                    <div className="mt-2 text-xs text-muted-foreground">
                      {question.whyItMatters}
                    </div>
                  ) : null}
                </AssistantMessage>
                <Field className="ml-auto max-w-[90%] sm:max-w-[82%]">
                  <FieldLabel className="sr-only" htmlFor={`answer-${question.id}`}>
                    {question.questionText}
                  </FieldLabel>
                  <Textarea
                    id={`answer-${question.id}`}
                    rows={3}
                    value={answers[question.id] ?? ""}
                    placeholder="What you did, where you did it, and the measurable outcome…"
                    onChange={(event) =>
                      setAnswers((currentAnswers) => ({
                        ...currentAnswers,
                        [question.id]: event.target.value,
                      }))
                    }
                  />
                </Field>
              </div>
            ))}
            {current.round.researchActions.length ? (
              <div className="flex flex-col gap-2">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Suggested evidence
                </div>
                {current.round.researchActions.map((action, index) => (
                  <ResearchActionControl action={action} key={`${action.kind}-${index}`} />
                ))}
              </div>
            ) : null}
            <div className="flex justify-end">
              <Button disabled={submit.isPending} onClick={() => void sendAnswers()}>
                {submit.isPending ? <Spinner data-icon="inline-start" /> : (
                  <Send data-icon="inline-start" aria-hidden="true" />
                )}
                Send answers
              </Button>
            </div>
          </div>
        ) : null}

        {!history.data?.rounds?.length && current.state === "idle" ? (
          <p className="text-sm text-muted-foreground">
            Start a round when you want focused questions about evidence gaps.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
