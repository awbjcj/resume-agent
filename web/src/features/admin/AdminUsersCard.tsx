import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Shield, Trash2, UserCog } from "lucide-react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, unwrap } from "@/lib/api/client";
export function AdminUsersCard({ currentUsername }: { currentUsername: string }) {
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => unwrap(api.GET("/api/admin/users")),
  });
  const patch = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: { role?: string; disabled?: boolean };
    }) =>
      unwrap(
        api.PATCH("/api/admin/users/{user_id}", {
          params: { path: { user_id: id } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/admin/users/{user_id}", {
          params: { path: { user_id: id }, query: { confirm: "DELETE" } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
  });

  if (users.isPending) return <Skeleton className="h-96 w-full" />;
  if (users.isError || !users.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Members are unavailable</AlertTitle>
        <AlertDescription>{users.error?.message ?? "Please try again."}</AlertDescription>
      </Alert>
    );
  }

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <UserCog aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle>
              <h3>Workspace members</h3>
            </CardTitle>
            <CardDescription>
              Review access, live usage, and account status from one roster.
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge variant="secondary">{users.data.users.length} accounts</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {patch.isError || remove.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Member update failed</AlertTitle>
            <AlertDescription>
              {patch.error?.message ?? remove.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Weekly usage</TableHead>
              <TableHead>Active jobs</TableHead>
              <TableHead>Quota policy</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.data.users.map((user) => {
              const isAdmin = user.role === "admin";
              const isCurrent = user.username === currentUsername;
              return (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <span className="font-medium">{user.username}</span>
                      <span className="text-xs text-muted-foreground">
                        Joined {new Date(user.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge variant={isAdmin ? "default" : "outline"}>{user.role}</Badge>
                      {user.disabledAt ? <Badge variant="destructive">Disabled</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {user.weeklyUsage.toLocaleString()}
                  </TableCell>
                  <TableCell className="tabular-nums">{user.activeJobs}</TableCell>
                  <TableCell>
                    {isAdmin ? (
                      <div className="flex flex-col items-start gap-1">
                        <Badge variant="secondary">Unlimited</Badge>
                        <span className="text-xs text-muted-foreground">
                          Tokens, jobs, and concurrency
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        Member defaults or overrides
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={patch.isPending}
                        onClick={() =>
                          patch.mutate({
                            id: user.id,
                            body: { role: isAdmin ? "user" : "admin" },
                          })
                        }
                      >
                        <Shield data-icon="inline-start" />
                        {isAdmin ? "Make member" : "Make admin"}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={patch.isPending || isCurrent}
                        onClick={() =>
                          patch.mutate({ id: user.id, body: { disabled: !user.disabledAt } })
                        }
                      >
                        {user.disabledAt ? "Enable" : "Disable"}
                      </Button>
                      <ConfirmDialog
                        trigger={
                          <Button
                            size="icon-sm"
                            variant="destructive"
                            aria-label={`Delete ${user.username}`}
                            disabled={isCurrent}
                          >
                            <Trash2 aria-hidden="true" />
                          </Button>
                        }
                        title={`Delete ${user.username}?`}
                        description="This permanently removes the user and their workspace."
                        confirmLabel="Delete"
                        onConfirm={async () => {
                          await remove.mutateAsync(user.id);
                        }}
                      />
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
