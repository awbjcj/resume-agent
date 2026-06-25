import * as React from "react";

import { cn } from "@/lib/utils";

type PopoverContextValue = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

type PopoverTriggerElementProps = {
  onClick?: React.MouseEventHandler<HTMLElement>;
  "aria-expanded"?: boolean;
};

const PopoverContext = React.createContext<PopoverContextValue | null>(null);

function Popover({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  return <PopoverContext.Provider value={{ open, setOpen }}>{children}</PopoverContext.Provider>;
}

function PopoverTrigger({
  render,
  children,
}: {
  render?: React.ReactElement<PopoverTriggerElementProps>;
  children?: React.ReactNode;
}) {
  const ctx = React.useContext(PopoverContext);
  if (!ctx) return null;
  const trigger = render ?? <button type="button">{children}</button>;
  if (!React.isValidElement<PopoverTriggerElementProps>(trigger)) return null;
  return React.cloneElement(trigger, {
    "aria-expanded": ctx.open,
    onClick: (event: React.MouseEvent<HTMLElement>) => {
      trigger.props.onClick?.(event);
      if (!event.defaultPrevented) ctx.setOpen(!ctx.open);
    },
  });
}

function PopoverContent({
  align = "start",
  className,
  ...props
}: React.ComponentProps<"div"> & { align?: "start" | "center" | "end" }) {
  const ctx = React.useContext(PopoverContext);
  if (!ctx?.open) return null;
  return (
    <div
      data-slot="popover-content"
      className={cn(
        "z-50 mt-2 rounded-lg border bg-popover text-popover-foreground shadow-md outline-none",
        align === "center" && "mx-auto",
        align === "end" && "ml-auto",
        className,
      )}
      {...props}
    />
  );
}

export { Popover, PopoverContent, PopoverTrigger };
