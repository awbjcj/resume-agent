import { useState } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

export function TagListInput({
  id, value, onChange, placeholder,
}: {
  id: string; value: string[]; onChange: (next: string[]) => void; placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const seen = new Set(value);
    const additions: string[] = [];
    for (const raw of draft.split(",")) {
      const tag = raw.trim();
      if (tag && !seen.has(tag)) {
        seen.add(tag);
        additions.push(tag);
      }
    }
    if (additions.length > 0) onChange([...value, ...additions]);
    setDraft("");
  };

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((tag) => (
            <Badge key={tag} variant="secondary" className="gap-1">
              {tag}
              <button
                type="button"
                aria-label={`Remove ${tag}`}
                className="rounded-sm hover:text-destructive"
                onClick={() => onChange(value.filter((t) => t !== tag))}
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        id={id}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && draft === "" && value.length > 0) {
            onChange(value.slice(0, -1));
          }
        }}
      />
    </div>
  );
}
