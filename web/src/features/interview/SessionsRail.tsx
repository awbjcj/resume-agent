import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ChatSessionHistory, type ChatSessionHistoryItem } from "@/components/chat/ChatSessionHistory";

import { NewInterviewDialog } from "./NewInterviewDialog";
import {
  useArchiveInterviewSession,
  useDeleteInterviewSession,
  useInterviewSessions,
  useRenameInterviewSession,
  useUnarchiveInterviewSession,
} from "./use-interview";

export function SessionsRail({ selectedId }: { selectedId: string | null }) {
  const navigate = useNavigate();
  const [showArchived, setShowArchived] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const sessions = useInterviewSessions(undefined, showArchived);
  const archive = useArchiveInterviewSession();
  const unarchive = useUnarchiveInterviewSession();
  const remove = useDeleteInterviewSession();
  const rename = useRenameInterviewSession();
  const items = useMemo<ChatSessionHistoryItem[]>(() => (sessions.data?.sessions ?? []).map((row) => {
    const fallbackTitle = [row.company, row.title].filter(Boolean).join(" · ") || "Mock interview";
    const title = row.sessionTitle || fallbackTitle;
    const progress = row.status === "active"
      ? `Question ${row.askedCount} of ${row.questionCount}`
      : row.overallScore != null ? `Scored ${row.overallScore}/5` : "Completed";
    return {
      id: row.sessionId,
      title,
      detail: `${row.sessionTitle ? `${fallbackTitle} · ` : ""}${progress} · ${new Date(row.startedAt).toLocaleDateString()}`,
      status: row.status === "active" ? "active" : "ended",
      archived: Boolean(row.archivedAt),
    };
  }), [sessions.data?.sessions]);

  return (
    <>
      <ChatSessionHistory
        ariaLabel="Interview sessions"
        items={items}
        selectedId={selectedId}
        onSelect={(sessionId) => navigate(`/interview?session=${encodeURIComponent(sessionId)}`)}
        showArchived={showArchived}
        onShowArchivedChange={setShowArchived}
        isLoading={sessions.isPending}
        isError={sessions.isError}
        onRetry={() => void sessions.refetch()}
        emptyMessage="No interview sessions yet. Start one when you are ready to practice."
        createLabel="New interview"
        onCreate={() => setNewOpen(true)}
        onRename={(sessionId, title) => rename.mutate({ sessionId, title })}
        onArchive={(sessionId) => archive.mutate({ sessionId }, {
          onSuccess: () => {
            if (sessionId === selectedId) navigate("/interview", { replace: true });
          },
        })}
        onUnarchive={(sessionId) => unarchive.mutate({ sessionId })}
        onDelete={(sessionId) => remove.mutate({ sessionId }, {
          onSuccess: () => {
            if (sessionId === selectedId) navigate("/interview", { replace: true });
          },
        })}
        renamePending={rename.isPending}
        deletePending={remove.isPending}
        deleteDescription={(item) => item.status === "active"
          ? "This interview is still in progress — deleting it abandons it without a debrief. This cannot be undone."
          : "The transcript and debrief will be permanently removed. This cannot be undone."}
      />
      <NewInterviewDialog open={newOpen} onOpenChange={setNewOpen} />
    </>
  );
}
