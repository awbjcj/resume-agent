import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff, Play, RotateCcw, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { authHeaders } from "@/lib/api/client";
import type { ChatPart } from "@/lib/chat/events";

import { TextPart } from "./TextPart";

type AudioChatPart = Extract<ChatPart, { kind: "audio" }>;

export function AudioPart({ part }: { part: AudioChatPart }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [objectUrl, setObjectUrl] = useState("");
  const [showText, setShowText] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [playBlocked, setPlayBlocked] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let localUrl = "";

    void fetch(part.url, {
      credentials: "include",
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Interview audio could not be loaded");
        localUrl = URL.createObjectURL(await response.blob());
        setObjectUrl(localUrl);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setLoadFailed(true);
        setShowText(true);
      });

    return () => {
      controller.abort();
      if (localUrl) URL.revokeObjectURL(localUrl);
    };
  }, [part.url]);

  useEffect(() => {
    if (!objectUrl || !part.autoPlay || !audio.current) return;
    void audio.current.play().catch(() => setPlayBlocked(true));
  }, [objectUrl, part.autoPlay]);

  const play = () => {
    if (!audio.current) return;
    audio.current.currentTime = 0;
    void audio.current.play().then(
      () => setPlayBlocked(false),
      () => setPlayBlocked(true),
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-primary/15 bg-primary/[0.045] p-3">
        <span className="flex size-9 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Volume2 className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-32 flex-1">
          <p className="text-sm font-medium text-foreground">Interviewer audio</p>
          <p className="text-xs text-muted-foreground" role="status">
            {loadFailed
              ? "Audio could not be loaded. The transcript is shown below."
              : objectUrl
                ? playBlocked
                  ? "Your browser blocked autoplay. Press play to listen."
                  : "AI-generated voice"
                : "Loading audio…"}
          </p>
        </div>
        {!loadFailed ? (
          <Button
            type="button"
            size="sm"
            variant={playBlocked ? "default" : "outline"}
            disabled={!objectUrl}
            aria-label={playBlocked ? "Play audio" : "Replay audio"}
            onClick={play}
          >
            {objectUrl ? (
              playBlocked ? <Play aria-hidden="true" /> : <RotateCcw aria-hidden="true" />
            ) : (
              <Spinner />
            )}
            {playBlocked ? "Play" : "Replay"}
          </Button>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label={showText ? "Hide text" : "Show text"}
          onClick={() => setShowText((visible) => !visible)}
        >
          {showText ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          {showText ? "Hide text" : "Show text"}
        </Button>
        {objectUrl ? <audio ref={audio} src={objectUrl} preload="auto" /> : null}
      </div>
      {showText ? <TextPart text={part.transcript} /> : null}
    </div>
  );
}
