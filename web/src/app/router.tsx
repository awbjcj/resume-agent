import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "./AppLayout";
import { ShortlistPage } from "@/features/shortlist/ShortlistPage";
import { PipelinePage } from "@/features/pipeline/PipelinePage";
import { TriagePage } from "@/features/triage/TriagePage";
import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";
import { MatchGapPage } from "@/features/match-gap/MatchGapPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <ShortlistPage /> },
      { path: "pipeline", element: <PipelinePage /> },
      { path: "triage", element: <TriagePage /> },
      { path: "analytics", element: <AnalyticsPage /> },
      { path: "match-gap", element: <MatchGapPage /> },
    ],
  },
]);
