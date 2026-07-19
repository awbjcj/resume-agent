import { CircleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useDismissAllErrors, useDismissError, useErrorRecords, useResolveError } from "@/features/errors/use-errors";

import { timeAgo } from "./time-ago";

export function AttentionCard() {
  const records = useErrorRecords("open");
  const dismiss = useDismissError();
  const resolve = useResolveError();
  const clearAll = useDismissAllErrors();
  const rows = records.data?.records ?? [];
  return <Card><CardHeader className="flex-row items-center justify-between gap-3"><CardTitle className="flex items-center gap-2 text-base"><CircleAlert className="text-destructive" aria-hidden="true" />Attention needed{rows.length ? <Badge variant="destructive">{rows.length}</Badge> : null}</CardTitle>{rows.length ? <Button size="sm" variant="outline" disabled={clearAll.isPending} onClick={() => clearAll.mutate()}>{clearAll.isPending ? <Spinner data-icon="inline-start" /> : null}Clear all</Button> : null}</CardHeader><CardContent>
    {records.isPending ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />Loading errors…</div> : null}
    {records.isError ? <Alert variant="destructive"><AlertTitle>Could not load errors</AlertTitle><AlertDescription className="flex items-center justify-between gap-3"><span>Recent failures are temporarily unavailable.</span><Button size="sm" variant="outline" onClick={() => void records.refetch()}>Try again</Button></AlertDescription></Alert> : null}
    {!records.isPending && !records.isError && !rows.length ? <p className="text-sm text-muted-foreground">No open errors.</p> : null}
    {rows.length ? <ul className="flex flex-col gap-3">{rows.map((row) => <li key={row.id} className="flex flex-wrap items-center gap-2 rounded-lg border p-3"><div className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{row.sourceLabel}</span><span className="text-xs text-muted-foreground">{row.message}{row.count > 1 ? ` · seen ${row.count}×` : ""} · {timeAgo(Date.parse(row.lastSeenAt))}</span></div><Button size="sm" variant="ghost" disabled={dismiss.isPending} onClick={() => dismiss.mutate({ id: row.id })}>Dismiss</Button><Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: row.id })}>Resolve</Button></li>)}</ul> : null}
  </CardContent></Card>;
}
