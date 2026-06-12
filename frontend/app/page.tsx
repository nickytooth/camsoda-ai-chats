"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "./hooks/useChat";
import ChatBubble from "./components/ChatBubble";
import ChatInput from "./components/ChatInput";
import TypingIndicator from "./components/TypingIndicator";
import ModeToggle from "./components/ModeToggle";
import ProfileSidebar from "./components/ProfileSidebar";
import NameScreen from "./components/NameScreen";
import { Circle } from "lucide-react";

const PROFILE = {
  name: "Victoria Donovan",
  tagline:
    "Your girlfriend's mother. Elegant, forbidden, and she knows exactly what she's doing.",
  profile: {
    age: "42",
    body: "Athletic",
    ethnicity: "European",
    language: "English",
    relationship: "Married",
    occupation: "Luxury real estate agent",
    hobbies: "Wine tasting, yoga, interior design",
    personality: "Refined, seductive, emotionally complex",
  },
};

/** Generate a stable numeric user ID from a name string */
function nameToId(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) & 0x7fffffff;
  }
  return Math.max(hash, 1);
}

export default function Home() {
  const [userName, setUserName] = useState<string | null>(null);
  const [userId, setUserId] = useState<number>(1);
  const [ready, setReady] = useState(false);

  // Load saved user from localStorage
  useEffect(() => {
    const saved = localStorage.getItem("victoria_user");
    if (saved) {
      const { name, id } = JSON.parse(saved);
      setUserName(name);
      setUserId(id);
    }
    setReady(true);
  }, []);

  const handleNameSubmit = (name: string) => {
    const id = nameToId(name);
    setUserName(name);
    setUserId(id);
    localStorage.setItem("victoria_user", JSON.stringify({ name, id }));
  };

  const handleReset = async () => {
    if (!userName) return;
    try {
      await fetch(`http://localhost:8000/api/reset?user_id=${userId}`, { method: "POST" });
    } catch (e) {}
    localStorage.removeItem("victoria_user");
    setUserName(null);
    setUserId(1);
  };

  if (!ready) return null;
  if (!userName) return <NameScreen onSubmit={handleNameSubmit} />;

  return <ChatView userName={userName} userId={userId} onReset={handleReset} />;
}

function ChatView({ userName, userId, onReset }: { userName: string; userId: number; onReset: () => void }) {
  const {
    messages,
    isTyping,
    isConnected,
    mode,
    isWaitingStory,
    sendMessage,
    switchMode,
  } = useChat({ userId, userName });

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages / typing
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  const inputDisabled = mode === "story" && isWaitingStory;

  return (
    <div className="flex h-screen">
      {/* ---- Chat area ---- */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-3 bg-[#111118] border-b border-[var(--border)]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-purple-600 to-pink-500 flex items-center justify-center text-sm font-bold text-white">
              V
            </div>
            <div>
              <span className="text-[15px] font-semibold text-white">
                Victoria
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <Circle
                  size={8}
                  className={`fill-current ${
                    isConnected ? "text-green-400" : "text-red-400"
                  }`}
                />
                <span className="text-[11px] text-[var(--muted)]">
                  {isTyping
                    ? "typing..."
                    : isConnected
                    ? "online"
                    : "offline"}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <ModeToggle mode={mode} onSwitch={switchMode} />
            <button
              onClick={onReset}
              className="px-3 py-1.5 text-[11px] rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
            >
              Reset
            </button>
          </div>
        </div>

        {/* Messages */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto py-4 bg-[var(--chat-bg)]"
        >
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-[var(--muted)] text-sm">
              Start a conversation...
            </div>
          )}
          {messages.map((msg) => (
            <ChatBubble
              key={msg.id}
              message={msg}
              isStory={mode === "story"}
            />
          ))}
          {isTyping && <TypingIndicator />}
        </div>

        {/* Input */}
        <ChatInput
          onSend={sendMessage}
          disabled={inputDisabled}
          placeholder={
            inputDisabled
              ? "Waiting for her response..."
              : mode === "story"
              ? "What do you do?"
              : "Write a message..."
          }
        />
      </div>

      {/* ---- Sidebar ---- */}
      <ProfileSidebar
        name={PROFILE.name}
        tagline={PROFILE.tagline}
        profile={PROFILE.profile}
      />
    </div>
  );
}
