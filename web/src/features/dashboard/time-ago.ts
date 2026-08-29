export function timeAgo(
  thenMs: number,
  nowMs: number = Date.now(),
  language: string = "en",
): string {
  const seconds = Math.max(0, Math.floor((nowMs - thenMs) / 1000));
  const chinese = language.toLowerCase().startsWith("zh");
  if (seconds < 60) return chinese ? "刚刚" : "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return chinese ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return chinese ? `${hours} 小时前` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return chinese ? `${days} 天前` : `${days}d ago`;
}
