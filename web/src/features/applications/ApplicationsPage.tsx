import { useMemo, useState } from "react";
import { Download, GitCompareArrows, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { openDownload } from "@/lib/api/client";
import { applicationStatusLabel } from "./application-labels";
import { ApplicationsTable } from "./ApplicationsTable";
import { RoleComparisonTable } from "./RoleComparisonTable";
import { useApplications } from "./use-applications";
import { useRoleComparison } from "./use-role-comparison";

type SortOrder = "newest" | "company-asc" | "company-desc" | "status";

export function ApplicationsPage() {
  const { t } = useTranslation();
  const query = useApplications();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState<SortOrder>("newest");
  const [selectedJobIds, setSelectedJobIds] = useState<number[]>([]);
  const comparison = useRoleComparison();
  const data = query.data;

  const visible = useMemo(() => {
    if (!data) return null;
    const needle = search.trim().toLocaleLowerCase();
    const rows = data.rows.filter(
      (row) =>
        (status === "all" || row.status === status) &&
        (!needle || `${row.company ?? ""} ${row.title ?? ""}`.toLocaleLowerCase().includes(needle)),
    );
    if (sort !== "newest") {
      rows.sort((left, right) => {
        if (sort === "status") return left.status.localeCompare(right.status);
        const compared = (left.company ?? "").localeCompare(right.company ?? "");
        return sort === "company-desc" ? -compared : compared;
      });
    }
    return { ...data, rows };
  }, [data, search, sort, status]);

  if (query.isPending || !visible) return <BoardSkeleton />;
  const statuses = [...new Set(data?.rows.map((row) => row.status) ?? [])].sort();
  const download = (shape: "wide" | "long") => {
    void openDownload(`/api/applications.csv?shape=${shape}`).catch((error: Error) =>
      toast.error(error.message),
    );
  };
  const toggleSelection = (jobId: number) => {
    comparison.reset();
    setSelectedJobIds((current) => {
      if (current.includes(jobId)) return current.filter((value) => value !== jobId);
      if (current.length === 3) {
        toast.error("Compare up to three roles at a time");
        return current;
      }
      return [...current, jobId];
    });
  };

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        kicker="Retrospective"
        title="Applications"
        sub="Read every application across the same timeline, then export the complete event history."
      />
      <section aria-label="Application controls" className="grid gap-3 rounded-lg border bg-card p-4 shadow-card md:grid-cols-[minmax(15rem,1fr)_11rem_13rem_auto] md:items-end">
        <label className="grid min-w-0 gap-1.5 text-sm font-medium" htmlFor="application-company-search">
          Company or role
          <span className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              id="application-company-search"
              className="pl-9"
              value={search}
              placeholder="Search applications"
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => event.key === "Escape" && setSearch("")}
            />
          </span>
        </label>
        <label className="grid gap-1.5 text-sm font-medium" htmlFor="application-status-filter">
          {t("applications.status")}
          <select id="application-status-filter" className="h-10 rounded-lg border bg-background px-3" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">{t("applications.allStatuses")}</option>
            {statuses.map((value) => <option key={value} value={value}>{applicationStatusLabel(t, value)}</option>)}
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium" htmlFor="application-sort">
          {t("applications.sortBy")}
          <select id="application-sort" className="h-10 rounded-lg border bg-background px-3" value={sort} onChange={(event) => setSort(event.target.value as SortOrder)}>
            <option value="newest">{t("applications.sortOptions.newest")}</option>
            <option value="company-asc">{t("applications.sortOptions.companyAscending")}</option>
            <option value="company-desc">{t("applications.sortOptions.companyDescending")}</option>
            <option value="status">{t("applications.sortOptions.status")}</option>
          </select>
        </label>
        <div className="flex flex-wrap gap-2 md:justify-end">
          <Button variant="outline" onClick={() => download("wide")}><Download aria-hidden="true" />Export grid</Button>
          <Button variant="outline" onClick={() => download("long")}><Download aria-hidden="true" />Export events</Button>
        </div>
      </section>
      <p className="text-sm text-muted-foreground" role="status">
        {t("applications.showing", { shown: visible.rows.length, total: data?.rows.length ?? 0 })}
      </p>
      <section aria-label="Role comparison controls" className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-4 shadow-card">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">Compare roles</p>
          <p className="text-sm text-muted-foreground">
            {`Select two or three application rows. ${selectedJobIds.length} selected.`}
          </p>
        </div>
        {selectedJobIds.length ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setSelectedJobIds([]);
              comparison.reset();
            }}
          >
            <X aria-hidden="true" />
            Clear
          </Button>
        ) : null}
        <Button
          type="button"
          disabled={selectedJobIds.length < 2 || comparison.isPending}
          onClick={() => comparison.mutate(selectedJobIds)}
        >
          <GitCompareArrows aria-hidden="true" />
          {comparison.isPending ? "Comparing…" : "Compare selected"}
        </Button>
      </section>
      {comparison.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Role comparison could not be loaded. The selected applications are unchanged.
        </p>
      ) : null}
      {comparison.data ? <RoleComparisonTable comparison={comparison.data} /> : null}
      <ApplicationsTable
        table={visible}
        selectedJobIds={selectedJobIds}
        onToggleSelection={toggleSelection}
      />
    </div>
  );
}
