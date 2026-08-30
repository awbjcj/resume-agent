import {
  AlertTriangle,
  Copy,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  UserSearch,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ACTIVE_RUN_STATUSES,
  latestArtifactRun,
  useArtifactRunIndex,
} from "@/features/job/artifact-runs";
import { useHiringContactIntelligence } from "@/features/job/use-company-research";
import { useRefreshHiringContactIntelligence } from "@/features/job/use-job-mutations";
import type { components } from "@/lib/api/schema";
import { ResearchNotice, ResearchPanelHeader } from "./ResearchPanel";

type Contact = components["schemas"]["HiringContactOut"];

function copyDraft(label: string, text: string) {
  void navigator.clipboard.writeText(text).then(() => toast.success(`${label} copied`));
}

function Draft({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-lg border bg-muted/25 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {label}
        </p>
        <Button
          type="button"
          size="xs"
          variant="ghost"
          aria-label={`Copy ${label.toLowerCase()}`}
          onClick={() => copyDraft(label, text)}
        >
          <Copy aria-hidden="true" />
          Copy
        </Button>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{text}</p>
    </div>
  );
}

function ContactCard({ contact }: { contact: Contact }) {
  return (
    <Card className="gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{contact.name}</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">{contact.publicRole}</p>
        </div>
        <Badge variant="outline">
          {contact.verificationState === "corroborated" ? "Corroborated" : "Single public source"}
        </Badge>
      </div>
      {contact.whyRelevant && <p className="text-sm leading-6">{contact.whyRelevant}</p>}
      <div className="flex flex-wrap gap-2">
        {(contact.sourceUrls ?? []).map((url) => (
          <a
            key={url}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/40 hover:text-primary"
          >
            Public source
            <ExternalLink className="size-3" aria-hidden="true" />
          </a>
        ))}
      </div>
      {contact.emailDraft && <Draft label="Email draft" text={contact.emailDraft} />}
      {contact.shortMessageDraft && (
        <Draft label="Short message draft" text={contact.shortMessageDraft} />
      )}
    </Card>
  );
}

export function HiringContactsPanel({ jobId }: { jobId: number }) {
  const query = useHiringContactIntelligence(jobId);
  const refresh = useRefreshHiringContactIntelligence(jobId);
  const run = latestArtifactRun(
    useArtifactRunIndex(),
    "hiringContactIntelligence",
    "jobId",
    jobId,
  );
  const researching = Boolean(run && ACTIVE_RUN_STATUSES.includes(run.status));
  const failed = run?.status === "failed";
  const resource = query.data;
  const intelligence = resource?.state === "ready" ? resource.intelligence : null;

  return (
    <section aria-labelledby="hiring-contacts-title" aria-busy={researching} className="space-y-4">
      <ResearchPanelHeader
        titleId="hiring-contacts-title"
        icon={<UserSearch className="size-5" aria-hidden="true" />}
        eyebrow="Public-source people research"
        title="Hiring contacts"
        description="Find publicly verified people who may be relevant to this role, then prepare copy-only drafts."
        context="No private enrichment, login-gated scraping, or automatic outreach."
        action={
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
            disabled={!resource?.canRefresh || researching}
            onClick={() => refresh.mutate()}
          >
            {researching ? (
              <LoaderCircle className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw aria-hidden="true" />
            )}
            {researching ? "Researching…" : intelligence ? "Refresh contacts" : "Research contacts"}
          </Button>
        }
      />

      <ResearchNotice icon={<AlertTriangle className="size-4" />}>
        Draft only. This feature never sends messages. Verify every person's current role before use.
      </ResearchNotice>

      {failed && (
        <ResearchNotice
          icon={<AlertTriangle className="size-4" />}
          className="border-destructive/30 bg-destructive/5 text-destructive"
          role="alert"
        >
          {run?.error ?? "Contact research failed. The last saved result is unchanged."}
        </ResearchNotice>
      )}

      {intelligence ? (
        <div className="space-y-4">
          {(intelligence.contacts ?? []).length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {(intelligence.contacts ?? []).map((contact) => (
                <ContactCard key={`${contact.name}:${contact.publicRole}`} contact={contact} />
              ))}
            </div>
          ) : (
            <ResearchNotice icon={<UserSearch className="size-4" />}>
              No named contact was confirmed from public sources.
            </ResearchNotice>
          )}
          <Card className="gap-3 p-5">
            <h3 className="font-semibold">Role-addressed drafts</h3>
            <p className="text-sm text-muted-foreground">
              Use these when no named person is verified or when a general recruiting channel is more appropriate.
            </p>
            <Draft label="Generic email draft" text={intelligence.genericEmailDraft} />
            <Draft label="Generic short message" text={intelligence.genericShortMessageDraft} />
          </Card>
        </div>
      ) : (
        <Card className="items-center gap-0 border-dashed px-6 py-10 text-center shadow-none">
          <UserSearch className="size-8 text-muted-foreground" aria-hidden="true" />
          <h3 className="mt-3 text-base font-semibold">No contact research yet</h3>
          <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
            {resource?.message ?? "Loading hiring-contact intelligence…"}
          </p>
        </Card>
      )}
    </section>
  );
}
