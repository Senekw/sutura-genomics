"use client";

import * as React from "react";
import { useState, useRef } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

interface ParticleButtonProps extends ButtonProps {
  onSuccess?: () => void;
  successDuration?: number;
}

function SuccessParticles({
  buttonRef,
}: {
  buttonRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const rect = buttonRef.current?.getBoundingClientRect();
  if (!rect) return null;

  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;

  return (
    <AnimatePresence>
      {[...Array(8)].map((_, i) => (
        <motion.div
          key={i}
          className="fixed z-[60] h-1.5 w-1.5 rounded-full bg-[#6633ee]"
          style={{ left: centerX, top: centerY }}
          initial={{ scale: 0, x: 0, y: 0, opacity: 1 }}
          animate={{
            scale: [0, 1, 0],
            x: [0, (i % 2 ? 1 : -1) * (Math.random() * 70 + 30)],
            y: [0, -Math.random() * 70 - 30],
            opacity: [1, 1, 0],
          }}
          transition={{
            duration: 0.7,
            delay: i * 0.06,
            ease: "easeOut",
          }}
        />
      ))}
    </AnimatePresence>
  );
}

function ParticleButton({
  children,
  onClick,
  onSuccess,
  successDuration = 800,
  className,
  ...props
}: ParticleButtonProps) {
  const [showParticles, setShowParticles] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    setShowParticles(true);
    onClick?.(e);
    window.setTimeout(() => {
      setShowParticles(false);
      onSuccess?.();
    }, successDuration);
  };

  return (
    <>
      {showParticles && <SuccessParticles buttonRef={buttonRef} />}
      <Button
        ref={buttonRef}
        onClick={handleClick}
        className={cn(
          "relative",
          showParticles && "scale-95",
          "transition-transform duration-100",
          className
        )}
        {...props}
      >
        {children}
      </Button>
    </>
  );
}

export { ParticleButton };
