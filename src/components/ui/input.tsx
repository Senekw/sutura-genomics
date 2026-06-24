"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

const ErrorIcon = () => (
  <svg
    height="13"
    width="13"
    viewBox="0 0 16 16"
    fill="currentColor"
    aria-hidden="true"
    className="shrink-0"
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M5.10051 0C4.83529 0 4.58094 0.105357 4.3934 0.292893L0.292893 4.3934C0.105357 4.58094 0 4.83529 0 5.10051V10.8995C0 11.1647 0.105357 11.4191 0.292894 11.6066L4.3934 15.7071C4.58094 15.8946 4.83529 16 5.10051 16H10.8995C11.1647 16 11.4191 15.8946 11.6066 15.7071L15.7071 11.6066C15.8946 11.4191 16 11.1647 16 10.8995V5.10051C16 4.83529 15.8946 4.58093 15.7071 4.3934L11.6066 0.292893C11.4191 0.105357 11.1647 0 10.8995 0H5.10051ZM8.75 3.75V8.75H7.25V3.75H8.75ZM8 12C8.55229 12 9 11.5523 9 11C9 10.4477 8.55229 10 8 10C7.44772 10 7 10.4477 7 11C7 11.5523 7.44772 12 8 12Z"
    />
  </svg>
);

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  required?: boolean;
  error?: string | boolean;
  wrapperClassName?: string;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, wrapperClassName, label, required, error, id, ...props }, ref) => {
    const reactId = React.useId();
    const inputId = id ?? reactId;
    const hasError = Boolean(error);

    return (
      <div className={cn("flex w-full flex-col gap-1.5", wrapperClassName)}>
        {label && (
          <label htmlFor={inputId} className="text-[13px] text-muted-foreground">
            {label}
            {required && <span className="ml-0.5 text-foreground/40">*</span>}
          </label>
        )}
        <input
          id={inputId}
          ref={ref}
          aria-invalid={hasError}
          className={cn(
            "h-11 w-full rounded-lg border bg-white px-3.5 text-sm text-foreground outline-none transition-all duration-150",
            "placeholder:text-muted-foreground/50",
            hasError
              ? "border-destructive focus:ring-2 focus:ring-destructive/20"
              : "border-input hover:border-muted-foreground/40 focus:border-ring focus:ring-2 focus:ring-ring/20",
            className
          )}
          {...props}
        />
        {typeof error === "string" && error.length > 0 && (
          <div className="flex items-center gap-1.5 text-[12.5px] text-destructive">
            <ErrorIcon />
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";

export { Input };
