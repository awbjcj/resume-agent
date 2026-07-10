import * as React from "react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ToggleContextValue = {
  value: string[];
  onValueChange: (value: string[]) => void;
};

const ToggleContext = React.createContext<ToggleContextValue | null>(null);

function ToggleGroup({
  value,
  onValueChange,
  className,
  ...props
}: Omit<React.ComponentProps<"div">, "onChange"> & {
  multiple?: boolean;
  value: string[];
  onValueChange: (value: string[]) => void;
}) {
  return (
    <ToggleContext.Provider value={{ value, onValueChange }}>
      <div
        data-slot="toggle-group"
        role="group"
        className={cn("flex flex-wrap items-center gap-1.5", className)}
        {...props}
      />
    </ToggleContext.Provider>
  );
}

function ToggleGroupItem({
  value,
  className,
  children,
  ...props
}: Omit<React.ComponentProps<"button">, "value"> & { value: string }) {
  const ctx = React.useContext(ToggleContext);
  const selected = Boolean(ctx?.value.includes(value));
  return (
    <button
      type="button"
      data-slot="toggle-group-item"
      aria-pressed={selected}
      className={cn(
        buttonVariants({ variant: selected ? "secondary" : "outline", size: "sm" }),
        "h-9 rounded-full px-3 text-sm",
        selected && "border-primary/40 text-primary",
        className,
      )}
      onClick={(event) => {
        props.onClick?.(event);
        if (event.defaultPrevented || !ctx) return;
        const next = selected
          ? ctx.value.filter((item) => item !== value)
          : [...ctx.value, value];
        ctx.onValueChange(next);
      }}
      {...props}
    >
      {children}
    </button>
  );
}

export { ToggleGroup, ToggleGroupItem };
