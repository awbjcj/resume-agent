import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppLayout } from "./AppLayout";
import { BoardSkeleton } from "@/components/skeletons";
import { SetupGate } from "@/features/setup/SetupGate";

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
const KeysSettingsPage = lazy(() =>
  import("@/features/settings/pages/KeysSettingsPage").then((m) => ({
    default: m.KeysSettingsPage,
  })),
);
const ReviewSettingsPage = lazy(() =>
  import("@/features/settings/pages/ReviewSettingsPage").then((m) => ({
    default: m.ReviewSettingsPage,
  })),
);
const RenderingSettingsPage = lazy(() =>
  import("@/features/settings/pages/RenderingSettingsPage").then((m) => ({
    default: m.RenderingSettingsPage,
  })),
);
const PruningSettingsPage = lazy(() =>
  import("@/features/settings/pages/PruningSettingsPage").then((m) => ({
    default: m.PruningSettingsPage,
  })),
);
const StyleGuideSettingsPage = lazy(() =>
  import("@/features/settings/pages/StyleGuideSettingsPage").then((m) => ({
    default: m.StyleGuideSettingsPage,
  })),
);
const ProfileSettingsPage = lazy(() =>
  import("@/features/settings/pages/ProfileSettingsPage").then((m) => ({
    default: m.ProfileSettingsPage,
  })),
);
const SetupWizard = lazy(() =>
  import("@/features/setup/SetupWizard").then((m) => ({ default: m.SetupWizard })),
);
const SetupIndexRedirect = lazy(() =>
  import("@/features/setup/SetupWizard").then((m) => ({ default: m.SetupIndexRedirect })),
);
const KeysStep = lazy(() =>
  import("@/features/setup/steps/KeysStep").then((m) => ({ default: m.KeysStep })),
);
const DocumentsStep = lazy(() =>
  import("@/features/setup/steps/DocumentsStep").then((m) => ({ default: m.DocumentsStep })),
);
const SearchStep = lazy(() =>
  import("@/features/setup/steps/SearchStep").then((m) => ({ default: m.SearchStep })),
);
const SourcesStep = lazy(() =>
  import("@/features/setup/steps/SourcesStep").then((m) => ({ default: m.SourcesStep })),
);
const FinishStep = lazy(() =>
  import("@/features/setup/FinishStep").then((m) => ({ default: m.FinishStep })),
);

const page = (node: ReactNode) => <Suspense fallback={<BoardSkeleton />}>{node}</Suspense>;

export const router = createBrowserRouter([
  {
    path: "/",
    element: <SetupGate><AppLayout /></SetupGate>,
    children: [
      { index: true, element: page(<ShortlistPage />) },
      { path: "pipeline", element: page(<PipelinePage />) },
      { path: "triage", element: page(<TriagePage />) },
      { path: "analytics", element: page(<AnalyticsPage />) },
      { path: "match-gap", element: page(<MatchGapPage />) },
      { path: "sources", element: <Navigate to="/settings/sources" replace /> },
      {
        path: "settings",
        element: page(<SettingsLayout />),
        children: [
          { index: true, element: <Navigate to="/settings/profile" replace /> },
          { path: "profile", element: page(<ProfileSettingsPage />) },
          { path: "search", element: page(<SearchSettingsPage />) },
          { path: "sources", element: page(<SourcesPage />) },
          { path: "keys", element: page(<KeysSettingsPage />) },
          { path: "review", element: page(<ReviewSettingsPage />) },
          { path: "rendering", element: page(<RenderingSettingsPage />) },
          { path: "pruning", element: page(<PruningSettingsPage />) },
          { path: "style-guide", element: page(<StyleGuideSettingsPage />) },
        ],
      },
    ],
  },
  {
    path: "/setup",
    element: page(<SetupWizard />),
    children: [
      { index: true, element: page(<SetupIndexRedirect />) },
      { path: "keys", element: page(<KeysStep />) },
      { path: "documents", element: page(<DocumentsStep />) },
      { path: "search", element: page(<SearchStep />) },
      { path: "sources", element: page(<SourcesStep />) },
      { path: "finish", element: page(<FinishStep />) },
    ],
  },
]);
