import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, RotateCcw, Square } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api/client";

type Phase = "idle" | "recording" | "uploading" | "failed";

async function upload(blob: Blob): Promise<string> {
  const body = new FormData();
  body.append("file", blob, "clip.webm");
  const response = await fetch("/api/transcribe", { method: "POST", body, credentials: "include" });
  if (!response.ok) throw new Error("Transcription failed");
  const data = (await response.json()) as { text: string };
  return data.text;
}

export function TranscribeButton({
  onText,
  disabled,
}: {
  onText: (text: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const blobRef = useRef<Blob | null>(null);

  const availability = useQuery({
    queryKey: ["transcribe-availability"],
    queryFn: () =>
      unwrap(api.GET("/api/transcribe/availability", {} as never)) as Promise<{
        available: boolean;
      }>,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (phase !== "recording") return;
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  if (!availability.data?.available) return null;

  const send = async (blob: Blob) => {
    blobRef.current = blob;
    setPhase("uploading");
    try {
      onText(await upload(blob));
      blobRef.current = null;
      setPhase("idle");
    } catch {
      toast.error("Transcription failed — tap retry");
      setPhase("failed");
    }
  };

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => chunksRef.current.push(event.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        void send(new Blob(chunksRef.current, { type: "audio/webm" }));
      };
      recorderRef.current = recorder;
      recorder.start();
      setElapsed(0);
      setPhase("recording");
    } catch {
      toast.error("Microphone access was denied");
    }
  };

  if (phase === "recording") {
    return (
      <Button
        type="button"
        variant="destructive"
        size="sm"
        onClick={() => recorderRef.current?.stop()}
        aria-label="Stop recording"
      >
        <Square className="h-4 w-4 animate-pulse" />
        <span className="ml-1 tabular-nums">{t("common.elapsedSeconds", { count: elapsed })}</span>
      </Button>
    );
  }
  // The icon-only phases use `icon-sm` so this button is the same 36px square as
  // the composer's send/stop control it sits beside; `recording` keeps the wider
  // `sm` size because it also renders the elapsed-seconds readout.
  if (phase === "uploading") {
    return (
      <Button type="button" variant="ghost" size="icon-sm" disabled aria-label="Transcribing">
        <Loader2 className="h-4 w-4 animate-spin" />
      </Button>
    );
  }
  if (phase === "failed") {
    return (
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        onClick={() => blobRef.current && void send(blobRef.current)}
        aria-label="Retry transcription"
      >
        <RotateCcw className="h-4 w-4" />
      </Button>
    );
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      disabled={disabled}
      onClick={() => void start()}
      aria-label="Record a voice answer"
    >
      <Mic className="h-4 w-4" />
    </Button>
  );
}
