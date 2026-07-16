import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { FilterState } from "@/lib/filters/types";

import type { Board } from "./use-board-query";

type BulkRequest = components["schemas"]["BulkRequest"];
type BulkResultOut = components["schemas"]["BulkResultOut"];
type Selection = { mode: "ids" | "query"; ids: Set<number> };

interface Args {
  action: "archive" | "restore" | "delete" | "approve" | "setStatus";
  selection: Selection;
  filter: FilterState;
  status?: string;
  archived?: boolean;
}

const SET_ARRAY: [keyof FilterState, keyof BulkRequest][] = [
  ["source", "source"],
  ["status", "statusIn"],
  ["remote", "remote"],
  ["sponsorship", "sponsorship"],
  ["seniority", "seniority"],
  ["employmentType", "employmentType"],
  ["industry", "industry"],
  ["country", "country"],
  ["region", "region"],
  ["city", "city"],
  ["companySize", "companySize"],
  ["skills", "skills"],
];

function buildBody(board: Board, args: Args, dryRun: boolean): BulkRequest {
  const filter = args.filter;
  const body: BulkRequest = {
    board,
    action: args.action,
    scope: args.selection.mode,
    dryRun,
    ids: [...args.selection.ids],
    status: args.status ?? null,
    archived: args.archived ?? false,
    q: filter.q.trim() || null,
    minFit: filter.fitMin,
    maxFit: filter.maxFit,
    minSalary: filter.salaryMin,
    staleDays: filter.staleDays,
    staleMinDays: filter.staleMinDays,
    sortBy: filter.sort,
    preset: filter.preset,
  };

  for (const [key, param] of SET_ARRAY) {
    (body[param] as string[]) = [...(filter[key] as Set<string>)];
  }
  return body;
}

export function useBulkAction(board: Board) {
  const qc = useQueryClient();
  const call = (args: Args, dryRun: boolean): Promise<BulkResultOut> =>
    unwrap(api.POST("/api/jobs/bulk", { body: buildBody(board, args, dryRun) as never }));

  return {
    preview: (args: Args) => call(args, true),
    run: async (args: Args) => {
      const result = await call(args, false);
      for (const key of ["shortlist", "pipeline", "triage"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      const skipped = result.skipped ? ` · ${result.skipped} skipped` : "";
      toast.success(`${args.action}: ${result.affected} job(s)${skipped}`);
      return result;
    },
  };
}
