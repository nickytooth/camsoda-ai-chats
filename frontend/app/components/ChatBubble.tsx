"use client";

import React, { useState, useEffect } from "react";
import { Lock, Check, CheckCheck } from "lucide-react";
import { ChatMessage, UnlockResult } from "../hooks/useChat";

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Render *italic actions* as actual <em> tags for story mode */
function renderContent(content: string, isStory: boolean) {
  if (!isStory) return content;

  const parts = content.split(/(\*[^*]+\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("*") && part.endsWith("*")) {
      return (
        <em key={i} className="text-purple-300/80 italic font-light">
          {part.slice(1, -1)}
        </em>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

interface Props {
  message: ChatMessage;
  isStory: boolean;
  showReceipt?: boolean;
  read?: boolean;
  onUnlock?: (photoUrl: string, messageId: string) => Promise<UnlockResult>;
  onTopUp?: () => Promise<void>;
}

export default function ChatBubble({ message, isStory, showReceipt, read, onUnlock, onTopUp }: Props) {
  const isUser = message.role === "user";

  // WhatsApp-style read receipts (sexting only), shown under EVERY user message
  // and kept there. A fresh message animates: one grey tick the instant it's
  // sent, then after ~1s flips to blue "Read" with double ticks — right as her
  // typing bubble appears. Already-read history messages render blue immediately.
  const [autoRead, setAutoRead] = useState(false);
  useEffect(() => {
    if (!isUser || !showReceipt || read) return;
    setAutoRead(false);
    const t = setTimeout(() => setAutoRead(true), 1000);
    return () => clearTimeout(t);
  }, [isUser, showReceipt, read, message.id]);

  const isRead = read || autoRead;

  let receipt: React.ReactNode = null;
  if (isUser && showReceipt) {
    receipt = isRead ? (
      <span className="inline-flex items-center gap-1">
        <span className="text-sky-400 font-medium">Read</span>
        <span>{formatTime(message.timestamp)}</span>
        <CheckCheck size={14} className="text-sky-400" />
      </span>
    ) : (
      <span className="inline-flex items-center gap-1">
        <span>{formatTime(message.timestamp)}</span>
        <Check size={14} className="text-[var(--muted)]" />
      </span>
    );
  }

  // A persisted upload (imageUrl, from history) or a live preview bubble whose
  // content is an [image:...] marker — both render as an image.
  const isImage = !!message.imageUrl || message.content.startsWith("[image:");

  const [unlocking, setUnlocking] = useState(false);
  const [unlockError, setUnlockError] = useState<string | null>(null);

  if (isImage) {
    const url = message.imageUrl ?? message.content.slice(7, -1);
    const locked = !!message.locked;
    const cost = message.cost ?? 10;

    const handleUnlock = async () => {
      if (!onUnlock || !message.photoUrl || unlocking) return;
      setUnlocking(true);
      setUnlockError(null);
      const result = await onUnlock(message.photoUrl, message.id);
      if (!result.ok) setUnlockError(result.error || "Couldn't unlock");
      setUnlocking(false);
    };

    return (
      <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3 px-4`}>
        <div className="max-w-[320px]">
          <div className="relative overflow-hidden rounded-2xl border border-[var(--border)]">
            <img
              src={url}
              alt=""
              className={`block w-full transition-all duration-500 ${
                locked ? "blur-2xl scale-110" : ""
              }`}
            />
            {locked && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/40 backdrop-blur-[2px] text-center px-4">
                <div className="w-11 h-11 rounded-full bg-white/15 flex items-center justify-center">
                  <Lock size={20} className="text-white" />
                </div>
                {unlockError ? (
                  <div className="flex flex-col items-center gap-2">
                    <span className="text-[12px] text-pink-200">{unlockError}</span>
                    {onTopUp && (
                      <button
                        onClick={() => { setUnlockError(null); onTopUp(); }}
                        className="px-3 py-1.5 text-[12px] font-semibold rounded-full bg-white/90 text-black hover:bg-white transition-colors"
                      >
                        Get more tokens
                      </button>
                    )}
                  </div>
                ) : (
                  <button
                    onClick={handleUnlock}
                    disabled={unlocking}
                    className="px-4 py-2 text-[13px] font-semibold rounded-full bg-gradient-to-r from-purple-600 to-pink-500 text-white shadow-lg hover:opacity-90 transition-opacity disabled:opacity-60"
                  >
                    {unlocking ? "Unlocking..." : `Unlock for ${cost} \u{1FA99}`}
                  </button>
                )}
              </div>
            )}
          </div>
          <div className={`text-[11px] text-[var(--muted)] mt-1 flex items-center gap-1 ${isUser ? "justify-end" : "justify-start"}`}>
            {receipt ?? formatTime(message.timestamp)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3 px-4`}>
      <div className="flex flex-col max-w-[70%]">
        {/* Avatar for her messages */}
        {!isUser && (
          <div className="flex items-end gap-2">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-purple-600 to-pink-500 flex-shrink-0 flex items-center justify-center text-[10px] font-bold text-white">
              V
            </div>
            <div className="bg-[var(--her-bubble)] rounded-2xl rounded-bl-md px-4 py-2.5 text-[14px] leading-relaxed">
              {renderContent(message.content, isStory)}
            </div>
          </div>
        )}

        {/* User messages */}
        {isUser && (
          <div className="bg-[var(--user-bubble)] rounded-2xl rounded-br-md px-4 py-2.5 text-[14px] leading-relaxed">
            {message.content}
          </div>
        )}

        {/* Timestamp */}
        <div
          className={`text-[11px] text-[var(--muted)] mt-1 flex items-center gap-1 ${
            isUser ? "justify-end pr-1" : "justify-start pl-9"
          }`}
        >
          {receipt ?? formatTime(message.timestamp)}
        </div>
      </div>
    </div>
  );
}
