import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function Command({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="command" className={cn("flex flex-col", className)} {...props} />;
}

function CommandInput({
  value,
  onValueChange,
  className,
  ...props
}: Omit<React.ComponentProps<typeof Input>, "onChange"> & {
  value: string;
  onValueChange: (value: string) => void;
}) {
  return (
    <div className="border-b p-2">
      <Input
        data-slot="command-input"
        className={cn("h-8", className)}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        {...props}
      />
    </div>
  );
}

function CommandList({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="command-list"
      className={cn("max-h-72 overflow-y-auto p-1", className)}
      {...props}
    />
  );
}

function CommandEmpty({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="command-empty"
      className={cn("px-2 py-6 text-center text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

function CommandGroup({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="command-group" className={cn("space-y-1", className)} {...props} />;
}

function CommandItem({
  className,
  onSelect,
  ...props
}: Omit<React.ComponentProps<"button">, "onSelect"> & {
  value?: string;
  onSelect?: () => void;
}) {
  return (
    <button
      type="button"
      data-slot="command-item"
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent",
        className,
      )}
      onClick={(event) => {
        props.onClick?.(event);
        if (!event.defaultPrevented) onSelect?.();
      }}
      {...props}
    />
  );
}

export { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList };
