import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppLayout } from "./AppLayout";
import { BoardSkeleton } from "@/components/skeletons";

// Route-level code-splitting: each page (and its heavy deps, e.g. recharts in
// Analytics) becomes its own chunk, keeping the initial bundle small.
const ShortlistPage = lazy(() =>
  import("@/features/shortlist/ShortlistPage").then((m) => ({ default: m.ShortlistPage })),
);
const PipelinePage = lazy(() =>
  import("@/features/pipeline/PipelinePage").then((m) => ({ default: m.PipelinePage })),
);
const TriagePage = lazy(() =>
  import("@/features/triage/TriagePage").then((m) => ({ default: m.TriagePage })),
);
const AnalyticsPage = lazy(() =>
  import("@/features/analytics/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })),
);
const MatchGapPage = lazy(() =>
  import("@/features/match-gap/MatchGapPage").then((m) => ({ default: m.MatchGapPage })),
);
const SourcesPage = lazy(() =>
  import("@/features/sources/SourcesPage").then((m) => ({ default: m.SourcesPage })),
);
const SettingsLayout = lazy(() =>
  import("@/features/settings/SettingsLayout").then((m) => ({ default: m.SettingsLayout })),
);
const SearchSettingsPage = lazy(() =>
  import("@/features/settings/pages/SearchSettingsPage").then((m) => ({
    default: m.SearchSettingsPage,
  })),
);

const page = (node: ReactNode) => <Suspense fallback={<BoardSkeleton />}>{node}</Suspense>;

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: page(<ShortlistPage />) },
      { path: "pipeline", element: page(<PipelinePage />) },
      { path: "triage", element: page(<TriagePage />) },
      { path: "analytics", element: page(<AnalyticsPage />) },
      { path: "match-gap", element: page(<MatchGapPage />) },
      { path: "sources", element: page(<SourcesPage />) },
      {
        path: "settings",
        element: page(<SettingsLayout />),
        children: [
          { index: true, element: <Navigate to="/settings/profile" replace /> },
          { path: "search", element: page(<SearchSettingsPage />) },
        ],
      },
    ],
  },
]);
