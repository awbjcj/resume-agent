export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div
      role="status"
      className="rounded-lg border border-dashed bg-card/80 px-6 py-14 text-center shadow-card"
    >
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mx-auto mt-2 max-w-[52ch] text-sm leading-6 text-muted-foreground">{body}</p>
    </div>
  );
}
