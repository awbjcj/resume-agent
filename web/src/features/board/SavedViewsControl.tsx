import { BookmarkIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { paramsToState, stateToParams } from "@/features/shortlist/use-board-filters";
import type { FilterState, SortKey } from "@/lib/filters/types";

import {
  type BoardName,
  useCreateSavedBoardView,
  useDeleteSavedBoardView,
  useSavedBoardViews,
} from "./use-saved-views";

export function SavedViewsControl({
  board,
  filter,
  defaultSort,
  extraQuery,
  onApply,
}: {
  board: BoardName;
  filter: FilterState;
  defaultSort: SortKey;
  extraQuery?: Readonly<Record<string, string | null | undefined>>;
  onApply: (filter: FilterState, params: URLSearchParams) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const views = useSavedBoardViews(board);
  const createView = useCreateSavedBoardView(board);
  const deleteView = useDeleteSavedBoardView(board);
  const trimmedName = name.trim();

  const save = () => {
    if (!trimmedName) return;
    const params = stateToParams(filter, defaultSort);
    for (const [key, value] of Object.entries(extraQuery ?? {})) {
      if (value == null) params.delete(key);
      else params.set(key, value);
    }
    createView.mutate(
      {
        name: trimmedName,
        queryString: params.toString(),
      },
      {
        onSuccess: () => {
          setName("");
          toast.success(`Saved view “${trimmedName}”`);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button type="button" variant="outline" size="xs">
            <BookmarkIcon aria-hidden="true" />
            Views
          </Button>
        }
      />
      <PopoverContent align="end" className="w-80">
        <PopoverHeader>
          <PopoverTitle>Saved views</PopoverTitle>
          <PopoverDescription>
            Reopen a named filter set for this board.
          </PopoverDescription>
        </PopoverHeader>

        <div className="max-h-52 space-y-1 overflow-y-auto">
          {views.isLoading ? (
            <p className="py-2 text-xs text-muted-foreground">Loading views…</p>
          ) : views.data?.length ? (
            views.data.map((view) => (
              <div key={view.id} className="flex items-center gap-1 rounded-md hover:bg-muted">
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate px-2 py-2 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => {
                    const params = new URLSearchParams(view.queryString);
                    onApply(
                      paramsToState(params, defaultSort),
                      params,
                    );
                    setOpen(false);
                  }}
                >
                  {view.name}
                </button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Delete ${view.name}`}
                  disabled={deleteView.isPending}
                  onClick={() =>
                    deleteView.mutate(view.id, {
                      onError: (error) => toast.error(error.message),
                    })
                  }
                >
                  <Trash2Icon aria-hidden="true" />
                </Button>
              </div>
            ))
          ) : (
            <p className="py-2 text-xs text-muted-foreground">No saved views yet.</p>
          )}
        </div>

        <form
          className="flex gap-2 border-t pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <Input
            aria-label="View name"
            placeholder="Name this view"
            maxLength={80}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" size="sm" disabled={!trimmedName || createView.isPending}>
            Save
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
