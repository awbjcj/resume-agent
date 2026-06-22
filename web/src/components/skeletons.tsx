import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function JobCardSkeleton() {
  return (
    <Card className="flex-row gap-4 p-4">
      <Skeleton className="h-12 w-10 rounded-md" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-5 w-2/3 rounded-md" />
        <Skeleton className="h-4 w-1/2 rounded-md" />
        <div className="flex gap-1 pt-1">
          <Skeleton className="h-5 w-12 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-10 rounded-full" />
        </div>
      </div>
    </Card>
  );
}

export function BoardSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading jobs"
      className="grid grid-cols-1 gap-4 xl:grid-cols-2"
    >
      {Array.from({ length: count }).map((_, index) => (
        <JobCardSkeleton key={index} />
      ))}
    </div>
  );
}

export function DrawerSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading job" className="mt-8 space-y-3">
      <Skeleton className="h-7 w-2/3 rounded-md" />
      <Skeleton className="h-4 w-1/2 rounded-md" />
      <Skeleton className="mt-6 h-40 w-full rounded-lg" />
    </div>
  );
}
