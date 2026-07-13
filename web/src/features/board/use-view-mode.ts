import { useSearchParams } from "react-router-dom";

export type ViewMode = "cards" | "list";

function isViewMode(value: string | null): value is ViewMode {
  return value === "cards" || value === "list";
}

export function useViewMode(storageKey = "board-view"): [ViewMode, (view: ViewMode) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlView = searchParams.get("view");
  const storedView = localStorage.getItem(storageKey);
  const view = isViewMode(urlView) ? urlView : isViewMode(storedView) ? storedView : "cards";

  const setView = (nextView: ViewMode) => {
    localStorage.setItem(storageKey, nextView);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("view", nextView);
      return next;
    }, { replace: true });
  };
  return [view, setView];
}
