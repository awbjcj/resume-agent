export function SkillChip({ name, active }: { name: string; active?: boolean }) {
  return (
    <span
      className={`inline-block rounded-sm border border-border px-2 py-0.5 text-xs ${
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground"
      }`}
    >
      {name}
    </span>
  );
}
