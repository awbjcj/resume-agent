import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StatusBadge } from "./StatusBadge";
import { DrawerSkeleton } from "./skeletons";
import { ApplicationEditor } from "@/features/job/ApplicationEditor";
import { StageManager } from "@/features/job/StageManager";
import { useJobDetail } from "@/features/job/use-job-detail";
import { useRenderVersion } from "@/features/job/use-job-mutations";

export function JobDrawer({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const { data: job, isLoading } = useJobDetail(jobId);
  const render = useRenderVersion(jobId);

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-xl">
        {isLoading || !job ? (
          <DrawerSkeleton />
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="font-serif text-2xl">{job.title ?? "—"}</SheetTitle>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                {job.company ?? "—"} · {job.location ?? "location n/a"}
                <StatusBadge status={job.status} />
              </div>
            </SheetHeader>
            <ScrollArea className="flex-1 px-4 pb-4">
              <Tabs defaultValue="jd" className="mt-2">
                <TabsList>
                  <TabsTrigger value="jd">Job description</TabsTrigger>
                  <TabsTrigger value="versions">Versions</TabsTrigger>
                  <TabsTrigger value="application">Application</TabsTrigger>
                  <TabsTrigger value="manage">Manage</TabsTrigger>
                </TabsList>
                <TabsContent value="jd">
                  {job.fitRationale && <p className="mb-3 text-sm">{job.fitRationale}</p>}
                  <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    Job description
                  </h3>
                  <pre className="mt-1 font-sans text-sm whitespace-pre-wrap">{job.jdText}</pre>
                </TabsContent>
                <TabsContent value="versions">
                  <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    Resume versions
                  </h3>
                  {job.resumeVersions.length === 0 && (
                    <p className="text-sm text-muted-foreground">Not tailored yet.</p>
                  )}
                  <ul className="mt-2 space-y-2">
                    {job.resumeVersions.map((v) => (
                      <li
                        key={v.id}
                        className="flex items-center justify-between rounded-md border p-2"
                      >
                        <span className="text-sm">
                          Round {v.round} · score {v.reviewScore ?? "—"} ·{" "}
                          {v.factCheckPassed ? "fact-check ✓" : "fact-check ✗"}
                        </span>
                        {v.pdfPath ? (
                          <a
                            className="text-sm underline"
                            href={`/api/resume-versions/${v.id}/pdf`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Download PDF
                          </a>
                        ) : (
                          <Button size="sm" variant="outline" onClick={() => render.mutate(v.id)}>
                            Render
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                </TabsContent>
                <TabsContent value="application">
                  <ApplicationEditor jobId={jobId} application={job.application} />
                </TabsContent>
                <TabsContent value="manage">
                  <StageManager job={job} onDeleted={onClose} />
                </TabsContent>
              </Tabs>
            </ScrollArea>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
