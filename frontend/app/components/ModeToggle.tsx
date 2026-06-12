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
        onClick={() => onSwitch("story")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-all ${
          mode === "story"
            ? "bg-gradient-to-r from-purple-600 to-purple-500 text-white shadow-md"
            : "text-[var(--muted)] hover:text-white"
        }`}
      >
        <BookOpen size={14} />
        Story
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
