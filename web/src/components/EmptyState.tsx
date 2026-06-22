export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div role="status" className="py-12 text-center">
      <h2 className="font-serif text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
    </div>
  );
}
