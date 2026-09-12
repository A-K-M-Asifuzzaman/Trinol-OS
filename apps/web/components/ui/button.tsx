import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex h-10 items-center justify-center rounded px-4 text-sm font-semibold tracking-[-0.01em] transition-[background-color,color,border-color,transform,box-shadow] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-50",
        variant === "default" &&
          "bg-primary text-primary-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)),0_1px_2px_hsl(var(--foreground)/0.14)] hover:bg-foreground hover:shadow-[0_0_0_3px_hsl(var(--signal)/0.42)]",
        variant === "outline" &&
          "border border-border bg-white text-foreground shadow-[0_1px_0_hsl(var(--foreground)/0.05)] hover:border-foreground hover:bg-muted/50",
        variant === "ghost" && "hover:bg-muted/70",
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
