import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type SavedBoardViewCreate = components["schemas"]["SavedBoardViewCreate"];

export type BoardName = SavedBoardViewCreate["board"];
export type SavedBoardView = components["schemas"]["SavedBoardViewOut"];

const key = (board: BoardName) => ["board-views", board] as const;

export function useSavedBoardViews(board: BoardName) {
  return useQuery<SavedBoardView[]>({
    queryKey: key(board),
    queryFn: () =>
      unwrap(
        api.GET("/api/board-views", { params: { query: { board } } }),
      ),
  });
}

export function useCreateSavedBoardView(board: BoardName) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; queryString: string }) =>
      unwrap(
        api.POST("/api/board-views", {
          body: { board, ...input },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key(board) }),
  });
}

export function useDeleteSavedBoardView(board: BoardName) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.DELETE("/api/board-views/{view_id}", {
          params: { path: { view_id: id } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key(board) }),
  });
}
