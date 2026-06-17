"use client";

import { BookOpen, MessageCircleHeart } from "lucide-react";

interface Props {
  mode: "sexting" | "story";
  onSwitch: (mode: "sexting" | "story") => void;
}

export default function ModeToggle({ mode, onSwitch }: Props) {
  return (
    <div className="flex bg-[#1a1a2e] rounded-lg p-0.5 gap-0.5">
      <button
        type="button"
        disabled
        title="Story mode — coming soon"
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium text-[var(--muted)] opacity-50 cursor-not-allowed"
      >
        <BookOpen size={14} />
        Story
        <span className="ml-0.5 text-[9px] uppercase tracking-wide px-1 py-0.5 rounded bg-white/10 text-[var(--muted)]">
          soon
        </span>
      </button>
      <button
        onClick={() => onSwitch("sexting")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-all ${
          mode === "sexting"
            ? "bg-gradient-to-r from-pink-600 to-purple-500 text-white shadow-md"
            : "text-[var(--muted)] hover:text-white"
        }`}
      >
        <MessageCircleHeart size={14} />
        Sexting
      </button>
    </div>
  );
}
