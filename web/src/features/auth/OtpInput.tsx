import { useRef, type ClipboardEvent, type KeyboardEvent } from "react";

const LENGTH = 6;

export function OtpInput({
  value,
  onChange,
  disabled,
  label,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  label: string;
}) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = Array.from({ length: LENGTH }, (_, index) => value[index] ?? "");
  const focus = (index: number) => refs.current[Math.max(0, Math.min(5, index))]?.focus();

  const typeDigit = (index: number, digit: string) => {
    if (!/^\d$/.test(digit)) return;
    const next = digits.slice();
    next[index] = digit;
    onChange(next.join("").slice(0, LENGTH));
    focus(index + 1);
  };

  const keyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (/^\d$/.test(event.key)) {
      event.preventDefault();
      typeDigit(index, event.key);
    } else if (event.key === "Backspace") {
      event.preventDefault();
      if (digits[index]) onChange(value.slice(0, index));
      else {
        onChange(value.slice(0, Math.max(0, index - 1)));
        focus(index - 1);
      }
    } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      focus(index + (event.key === "ArrowLeft" ? -1 : 1));
    }
  };

  const paste = (event: ClipboardEvent<HTMLInputElement>) => {
    const next = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, LENGTH);
    if (!next) return;
    event.preventDefault();
    onChange(next);
    focus(Math.min(next.length, LENGTH - 1));
  };

  return (
    <div role="group" aria-label={label} className="grid grid-cols-6 gap-2">
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(node) => {
            refs.current[index] = node;
          }}
          type="text"
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          aria-label={`Digit ${index + 1}`}
          value={digit}
          disabled={disabled}
          onChange={(event) => typeDigit(index, event.target.value.slice(-1))}
          onKeyDown={(event) => keyDown(index, event)}
          onPaste={paste}
          className="aspect-square min-w-0 rounded-md border border-input bg-transparent text-center text-lg tabular-nums shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
        />
      ))}
    </div>
  );
}
