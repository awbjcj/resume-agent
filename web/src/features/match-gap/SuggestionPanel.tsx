import {
  BookOpen,
  ExternalLink,
  GitFork,
  Hammer,
  Lightbulb,
  Star,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { SuggestionEnvelope } from "./use-suggestion";

export function SuggestionPanel({
  envelope,
  isLoading,
  isError = false,
  onRetry = () => {},
  onGenerate,
  generating,
}: {
  envelope: SuggestionEnvelope | undefined;
  isLoading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  onGenerate: () => void;
  generating: boolean;
}) {
  if (isLoading) {
    return (
      <div role="status" aria-busy="true" aria-label="Loading gap-closing advice" className="space-y-3">
        <Skeleton className="h-4 w-2/5" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div role="alert" className="border-l-2 border-destructive pl-3 text-sm">
        <p className="font-medium">Couldn't load cached advice.</p>
        <p className="mt-1 text-muted-foreground">Retry the request without closing this panel.</p>
        <Button className="mt-3" size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      </div>
    );
  }

  const suggestion = envelope?.suggestion;
  if (!suggestion) {
    return (
      <div className="border-l-2 border-primary/45 pl-4">
        <p className="text-sm font-medium">No advice cached yet</p>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Research verified repositories, learning resources, and a portfolio project on demand.
        </p>
        <Button className="mt-3" size="sm" disabled={generating} onClick={onGenerate}>
          <Lightbulb data-icon="inline-start" />
          {generating ? "Researching…" : "How to close this gap"}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold">How to close this gap</h2>
          {envelope.stale && <Badge variant="outline">Stale</Badge>}
        </div>
        <Button size="sm" variant="outline" disabled={generating} onClick={onGenerate}>
          {generating ? "Researching…" : "Regenerate"}
        </Button>
      </div>

      {suggestion.bridge && (
        <div className="border-l-2 border-primary pl-4">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">
            Your bridge
          </p>
          <p className="mt-2 leading-6 text-muted-foreground">{suggestion.bridge}</p>
        </div>
      )}

      {suggestion.repos.length > 0 && (
        <section aria-labelledby="advisor-repositories">
          <h3 id="advisor-repositories" className="flex items-center gap-2 font-semibold">
            <GitFork className="size-4 text-primary" />
            Repositories to learn from
          </h3>
          <ul className="mt-3 divide-y border-y">
            {suggestion.repos.map((repository) => (
              <li key={repository.url} className="py-3">
                <div className="flex items-start justify-between gap-3">
                  <a
                    className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                    href={repository.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {repository.name}
                    <ExternalLink className="size-3" />
                  </a>
                  {typeof repository.stars === "number" && (
                    <span className="flex shrink-0 items-center gap-1 font-mono text-xs text-muted-foreground">
                      <Star className="size-3" />
                      {repository.stars.toLocaleString()}
                    </span>
                  )}
                </div>
                {repository.description && (
                  <p className="mt-1 text-muted-foreground">{repository.description}</p>
                )}
                {repository.why && <p className="mt-1 text-xs leading-5">{repository.why}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {suggestion.resources.length > 0 && (
        <section aria-labelledby="advisor-resources">
          <h3 id="advisor-resources" className="flex items-center gap-2 font-semibold">
            <BookOpen className="size-4 text-primary" />
            Learning resources
          </h3>
          <ul className="mt-3 divide-y border-y">
            {suggestion.resources.map((resource) => (
              <li key={resource.url} className="flex items-center justify-between gap-3 py-3">
                <a
                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                  href={resource.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {resource.title}
                  <ExternalLink className="size-3" />
                </a>
                <Badge variant="secondary">{resource.kind}</Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      {suggestion.project && (
        <section aria-labelledby="advisor-project" className="border-y bg-accent/35 px-4 py-4">
          <h3 id="advisor-project" className="flex items-center gap-2 font-semibold">
            <Hammer className="size-4 text-primary" />
            Build this
          </h3>
          <p className="mt-3 font-medium">{suggestion.project.title}</p>
          <p className="mt-1 leading-6 text-muted-foreground">{suggestion.project.summary}</p>
          {suggestion.project.skillsDemonstrated.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {suggestion.project.skillsDemonstrated.map((skill) => (
                <Badge key={skill} variant="outline">
                  {skill}
                </Badge>
              ))}
            </div>
          )}
        </section>
      )}

      {suggestion.citations.length > 0 && (
        <details className="border-t pt-4">
          <summary className="cursor-pointer font-medium">Sources</summary>
          <ul className="mt-3 space-y-2 break-all text-xs">
            {suggestion.citations.map((url) => (
              <li key={url}>
                <a
                  className="text-primary underline underline-offset-2"
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
