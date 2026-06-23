export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div
      role="status"
      className="rounded-lg border border-dashed bg-card/80 px-6 py-14 text-center shadow-[0_1px_2px_rgba(24,32,38,0.04)]"
    >
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mx-auto mt-2 max-w-[52ch] text-sm leading-6 text-muted-foreground">{body}</p>
    </div>
  );
}
