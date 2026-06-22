import { Badge } from "@/components/ui/badge";

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className="font-mono text-[0.65rem] uppercase tracking-wider">
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
