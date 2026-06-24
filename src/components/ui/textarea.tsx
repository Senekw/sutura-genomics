"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  required?: boolean;
  error?: string | boolean;
  wrapperClassName?: string;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, wrapperClassName, label, required, error, id, ...props }, ref) => {
    const reactId = React.useId();
    const textareaId = id ?? reactId;
    const hasError = Boolean(error);

    return (
      <div className={cn("flex w-full flex-col gap-1.5", wrapperClassName)}>
        {label && (
          <label htmlFor={textareaId} className="text-[13px] text-muted-foreground">
            {label}
            {required && <span className="ml-0.5 text-foreground/40">*</span>}
          </label>
        )}
        <textarea
          id={textareaId}
          ref={ref}
          aria-invalid={hasError}
          className={cn(
            "min-h-[88px] w-full rounded-lg border bg-white px-3.5 py-2.5 text-sm text-foreground outline-none transition-all duration-150",
            "placeholder:text-muted-foreground/50",
            hasError
              ? "border-destructive focus:ring-2 focus:ring-destructive/20"
              : "border-input hover:border-muted-foreground/40 focus:border-ring focus:ring-2 focus:ring-ring/20",
            className
          )}
          {...props}
        />
        {typeof error === "string" && error.length > 0 && (
          <span className="text-[12.5px] text-destructive">{error}</span>
        )}
      </div>
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
