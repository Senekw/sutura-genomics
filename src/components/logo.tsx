import Image from "next/image";
import { cn } from "@/lib/utils";

export function Logo({
  size = 44,
  withWordmark = true,
  className,
}: {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <Image
        src="/sutura-logo.png"
        alt="Sutura Genomics logo"
        width={size}
        height={size}
        priority
        className="shrink-0 object-contain"
        style={{ width: size, height: size }}
      />
      {withWordmark && (
        <span className="text-2xl font-light tracking-tight text-foreground">
          Sutura Genomics
        </span>
      )}
    </div>
  );
}
