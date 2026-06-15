"use client";

import React, { useState, useRef } from "react";
import { Send, Paperclip, Sparkles, Loader2 } from "lucide-react";

interface Props {
  onSend: (text: string, imageBase64?: string) => void;
  onSuggest?: () => Promise<string>;
  disabled?: boolean;
  placeholder?: string;
}

export default function ChatInput({ onSend, onSuggest, disabled, placeholder }: Props) {
  const [text, setText] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSuggest = async () => {
    if (!onSuggest || suggesting || disabled) return;
    setSuggesting(true);
    try {
      const suggestion = await onSuggest();
      if (suggestion) {
        setText(suggestion);
        inputRef.current?.focus();
      }
    } finally {
      setSuggesting(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      const base64 = (reader.result as string).split(",")[1];
      onSend(text.trim() || "", base64);
      setText("");
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-center gap-2 px-4 py-3 bg-[#111118] border-t border-[var(--border)]"
    >
      {/* Attachment */}
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        className="p-2 text-[var(--muted)] hover:text-[var(--accent)] transition-colors"
        title="Send photo"
      >
        <Paperclip size={20} />
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFile}
      />

      {/* AI Help — draft a reply */}
      {onSuggest && (
        <button
          type="button"
          onClick={handleSuggest}
          disabled={disabled || suggesting}
          title="AI Help — draft a reply"
          className="p-2 text-[var(--muted)] hover:text-[var(--accent)] transition-colors disabled:opacity-40"
        >
          {suggesting ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <Sparkles size={20} />
          )}
        </button>
      )}

      {/* Text input */}
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={suggesting ? "Drafting a reply..." : placeholder || "Write a message..."}
        disabled={disabled}
        className="flex-1 bg-[#1a1a2e] text-[var(--foreground)] placeholder-[var(--muted)] rounded-xl px-4 py-2.5 text-[14px] outline-none focus:ring-1 focus:ring-[var(--accent)]/50 disabled:opacity-50"
      />

      {/* Send */}
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        className="p-2.5 bg-gradient-to-r from-purple-600 to-pink-500 rounded-xl text-white disabled:opacity-30 hover:opacity-90 transition-opacity"
      >
        <Send size={18} />
      </button>
    </form>
  );
}
