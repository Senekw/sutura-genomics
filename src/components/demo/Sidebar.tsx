"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Database, Activity, Settings, LogOut } from "lucide-react";

import { Logo } from "@/components/logo";
import { signOut } from "@/lib/demoAuth";

const NAV = [
  { key: "datasets", label: "Datasets", icon: Database, href: "/demo/dashboard" },
  { key: "runs", label: "Runs", icon: Activity, href: "/demo/runs" },
  { key: "settings", label: "Settings", icon: Settings, href: "/demo/settings" },
] as const;

export default function Sidebar({ active }: { active: "datasets" | "runs" | "settings" }) {
  const router = useRouter();
  const onLogout = () => {
    signOut();
    router.replace("/demo/login");
  };
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-white/70 px-4 py-6 backdrop-blur-sm sm:flex">
      <div className="px-2">
        <Logo size={30} withWordmark />
      </div>
      <nav className="mt-9 flex flex-col gap-1">
        {NAV.map((item) => {
          const isActive = item.key === active;
          const Icon = item.icon;
          return (
            <Link
              key={item.key}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-light transition-colors " +
                (isActive
                  ? "bg-[#6633ee]/10 text-[#6633ee]"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground")
              }
            >
              <Icon className="h-[17px] w-[17px]" strokeWidth={isActive ? 2 : 1.6} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <button
        type="button"
        onClick={onLogout}
        className="mt-auto flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-light text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        <LogOut className="h-[17px] w-[17px]" strokeWidth={1.6} />
        Sign out
      </button>
    </aside>
  );
}
