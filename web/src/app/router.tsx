import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppLayout } from "./AppLayout";
import { BoardSkeleton } from "@/components/skeletons";
import { SetupGate } from "@/features/setup/SetupGate";
import { AuthGate } from "@/features/auth/AuthGate";

// Route-level code-splitting: each page (and its heavy deps, e.g. recharts in
// Analytics) becomes its own chunk, keeping the initial bundle small.
const DashboardPage = lazy(() =>
  import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
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
const CoachPage = lazy(() =>
  import("@/features/coach/CoachPage").then((m) => ({ default: m.CoachPage })),
);
const InterviewPage = lazy(() =>
  import("@/features/interview/InterviewPage").then((m) => ({ default: m.InterviewPage })),
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
const AgentPromptsPage = lazy(() =>
  import("@/features/settings/pages/AgentPromptsPage").then((m) => ({
    default: m.AgentPromptsPage,
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
const LoginPage = lazy(() =>
  import("@/features/auth/LoginPage").then((m) => ({ default: m.LoginPage })),
);
const RegisterPage = lazy(() =>
  import("@/features/auth/RegisterPage").then((m) => ({ default: m.RegisterPage })),
);
const AccountPage = lazy(() =>
  import("@/features/account/AccountPage").then((m) => ({ default: m.AccountPage })),
);
const AdminPage = lazy(() =>
  import("@/features/admin/AdminPage").then((m) => ({ default: m.AdminPage })),
);

const page = (node: ReactNode) => <Suspense fallback={<BoardSkeleton />}>{node}</Suspense>;

export const router = createBrowserRouter([
  { path: "/login", element: page(<LoginPage />) },
  { path: "/register", element: page(<RegisterPage />) },
  {
    path: "/",
    element: <AuthGate><AppLayout /></AuthGate>,
    children: [
      { index: true, element: <SetupGate>{page(<DashboardPage />)}</SetupGate> },
      { path: "shortlist", element: <SetupGate>{page(<ShortlistPage />)}</SetupGate> },
      { path: "pipeline", element: <SetupGate>{page(<PipelinePage />)}</SetupGate> },
      { path: "triage", element: <SetupGate>{page(<TriagePage />)}</SetupGate> },
      { path: "analytics", element: <SetupGate>{page(<AnalyticsPage />)}</SetupGate> },
      { path: "match-gap", element: <SetupGate>{page(<MatchGapPage />)}</SetupGate> },
      { path: "coach", element: <SetupGate>{page(<CoachPage />)}</SetupGate> },
      { path: "interview", element: <SetupGate>{page(<InterviewPage />)}</SetupGate> },
      { path: "account", element: page(<AccountPage />) },
      { path: "admin", element: page(<AdminPage />) },
      { path: "sources", element: <Navigate to="/settings/sources" replace /> },
      {
        path: "settings",
        element: <SetupGate>{page(<SettingsLayout />)}</SetupGate>,
        children: [
          { index: true, element: <Navigate to="/settings/profile" replace /> },
          { path: "profile", element: page(<ProfileSettingsPage />) },
          { path: "search", element: page(<SearchSettingsPage />) },
          { path: "sources", element: page(<SourcesPage />) },
          { path: "keys", element: page(<KeysSettingsPage />) },
          { path: "review", element: page(<ReviewSettingsPage />) },
          { path: "agent-prompts", element: page(<AgentPromptsPage />) },
          { path: "rendering", element: page(<RenderingSettingsPage />) },
          { path: "pruning", element: page(<PruningSettingsPage />) },
          { path: "style-guide", element: page(<StyleGuideSettingsPage />) },
        ],
      },
    ],
  },
  {
    path: "/setup",
    element: <AuthGate>{page(<SetupWizard />)}</AuthGate>,
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
