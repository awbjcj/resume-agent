import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router-dom";

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
    ],
  },
]);
