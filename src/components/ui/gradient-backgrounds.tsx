import { cn } from "@/lib/utils";

interface GradientBackgroundProps {
  className?: string;
}

export const GradientBackground = ({ className }: GradientBackgroundProps) => {
  return (
    <div
      aria-hidden="true"
      className={cn("pointer-events-none absolute inset-0 -z-10", className)}
    >
      {/* deep base */}
      <div className="absolute inset-0 bg-background" />
      {/* indigo glow from the top */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(125% 125% at 50% 0%, transparent 40%, rgba(99, 102, 241, 0.18) 78%, rgba(99, 102, 241, 0.45) 100%)",
        }}
      />
      {/* soft top spotlight */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 0%, rgba(124, 108, 240, 0.16) 0%, transparent 70%)",
        }}
      />
      {/* subtle grid */}
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
          backgroundSize: "56px 56px",
          maskImage:
            "radial-gradient(ellipse 80% 60% at 50% 0%, #000 50%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 80% 60% at 50% 0%, #000 50%, transparent 100%)",
        }}
      />
    </div>
  );
};
