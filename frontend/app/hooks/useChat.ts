"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { API_BASE, WS_BASE } from "../api";
import type { StoryHeat } from "../components/StoryMeter";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  mode: "sexting" | "story";
  imageUrl?: string;
  // Pay-to-see selfies: `locked` blurs the image until unlocked, `cost` is the
  // token price, `photoUrl` is the relative /content path used for the unlock call.
  locked?: boolean;
  cost?: number;
  photoUrl?: string;
}

export interface UnlockResult {
  ok: boolean;
  balance: number;
  error?: string;
}

interface UseChatOptions {
  wsUrl?: string;
  userId?: number;
  userName?: string;
}

export function useChat({ wsUrl = `${WS_BASE}/ws/chat`, userId = 1, userName = "" }: UseChatOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [mode, setMode] = useState<"sexting" | "story">("sexting");
  const [isConnected, setIsConnected] = useState(false);
  const [isWaitingStory, setIsWaitingStory] = useState(false);
  const [balance, setBalance] = useState<number | null>(null);
  const [storyHeat, setStoryHeat] = useState<StoryHeat | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const idCounter = useRef(0);
  const openingAnimating = useRef(false);
  // The sexting opening is animated once per session. Without this, switching
  // away to story and back would replay the first bubbles every time, because
  // the (still unanswered) history is all-assistant and looks "fresh" again.
  const sextingOpeningPlayed = useRef(false);

  const genId = () => `msg-${Date.now()}-${idCounter.current++}`;

  // Load history for current mode
  const loadHistory = useCallback(async (m: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/history/${m}?user_id=${userId}`);
      if (!res.ok) return;
      const data = await res.json();
      const loaded: ChatMessage[] = (data.messages || []).map((msg: any) => ({
        id: genId(),
        role: msg.role,
        content: msg.content,
        timestamp: msg.timestamp,
        mode: m,
        // Stored as a relative path ("/uploads/..") — make it absolute against
        // the backend so the <img> resolves regardless of the frontend origin.
        imageUrl: msg.image_url
          ? msg.image_url.startsWith("http")
            ? msg.image_url
            : `${API_BASE}${msg.image_url}`
          : undefined,
        locked: msg.locked,
        cost: msg.cost,
        photoUrl: msg.image_url,
      }));

      // Fresh opening: Victoria initiated and the user hasn't replied yet
      // (every loaded message is from her). Play it out with the typing
      // indicator and send the bubbles one by one, instead of dumping them.
      const isFreshOpening =
        m === "sexting" &&
        loaded.length > 0 &&
        loaded.every((msg) => msg.role === "assistant");

      if (isFreshOpening) {
        // Guard against double-run (React StrictMode mounts effects twice in
        // dev, which would otherwise append every bubble twice).
        if (openingAnimating.current) return;
        // Already animated once this session (e.g. switched away and back):
        // just show the bubbles statically instead of replaying them.
        if (sextingOpeningPlayed.current) {
          setMessages(loaded);
          return;
        }
        openingAnimating.current = true;
        sextingOpeningPlayed.current = true;
        try {
          setMessages([]);
          for (let i = 0; i < loaded.length; i++) {
            setIsTyping(true);
            // Longer pause before the first bubble, a little shorter between the rest
            await new Promise((r) => setTimeout(r, i === 0 ? 2500 : 1300));
            setIsTyping(false);
            setMessages((prev) => [...prev, loaded[i]]);
            // small gap so consecutive bubbles don't appear in the same frame
            if (i < loaded.length - 1) {
              await new Promise((r) => setTimeout(r, 350));
            }
          }
        } finally {
          openingAnimating.current = false;
        }
        return;
      }

      setMessages(loaded);
    } catch (e) {
      console.error("Failed to load history:", e);
    }
  }, [userId]);

  // Connect WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`${wsUrl}?user_id=${userId}&user_name=${encodeURIComponent(userName)}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case "typing_start":
          setIsTyping(true);
          break;
        case "typing_end":
          setIsTyping(false);
          break;
        case "message":
          setIsTyping(false);
          setIsWaitingStory(false);
          const newMsg: ChatMessage = {
            id: genId(),
            role: data.role || "assistant",
            content: data.content,
            timestamp: data.timestamp || Date.now() / 1000,
            mode: data.mode || "sexting",
          };
          setMessages((prev) => [...prev, newMsg]);
          break;
        case "image":
          setIsTyping(false);
          const imageUrl = data.url?.startsWith("http") ? data.url : `${API_BASE}${data.url}`;
          const imgMsg: ChatMessage = {
            id: genId(),
            role: "assistant",
            content: `[image:${imageUrl}]`,
            timestamp: data.timestamp || Date.now() / 1000,
            mode: data.mode || "sexting",
            locked: data.locked,
            cost: data.cost,
            photoUrl: data.photo_url || data.url,
          };
          setMessages((prev) => [...prev, imgMsg]);
          break;
        case "story_heat":
          setStoryHeat({
            heat: data.heat,
            level: data.level,
            label: data.label,
            max_heat: data.max_heat,
            climax: data.climax,
            explicit: data.explicit,
          });
          break;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      console.log("WebSocket disconnected, reconnecting in 3s...");
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };
  }, [wsUrl, userId, userName]);

  // Send message
  const sendMessage = useCallback(
    (text: string, imageDataUrl?: string) => {
      if (!text.trim() && !imageDataUrl) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      const now = Date.now() / 1000;

      // Show the user's messages immediately: the photo as its own image
      // bubble (so it actually renders), plus a text bubble if there's text.
      const newMsgs: ChatMessage[] = [];
      if (imageDataUrl) {
        newMsgs.push({
          id: genId(),
          role: "user",
          content: `[image:${imageDataUrl}]`,
          timestamp: now,
          mode,
        });
      }
      if (text.trim()) {
        newMsgs.push({
          id: genId(),
          role: "user",
          content: text,
          timestamp: now,
          mode,
        });
      }
      setMessages((prev) => [...prev, ...newMsgs]);

      if (mode === "story") {
        setIsWaitingStory(true);
        // Show the typing indicator immediately so the "thinking" animation
        // runs during generation, not just right before the reply arrives.
        setIsTyping(true);
      }

      // Backend expects raw base64 (no "data:...;base64," prefix) for vision.
      const imageBase64 = imageDataUrl ? imageDataUrl.split(",")[1] : undefined;

      // Send via WebSocket
      wsRef.current.send(
        JSON.stringify({
          type: "message",
          content: text,
          mode,
          image: imageBase64 || undefined,
        })
      );
    },
    [mode]
  );

  // Card request (Hear a fantasy / Hear a story): show the user's request as a
  // bubble, then ask the backend to pull a (non-repeating) item from the library.
  const triggerCard = useCallback(
    (kind: "fantasy" | "story", requestText: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      setMessages((prev) => [
        ...prev,
        { id: genId(), role: "user", content: requestText, timestamp: Date.now() / 1000, mode },
      ]);
      setIsTyping(true);
      wsRef.current.send(JSON.stringify({ type: "card", kind, content: requestText, mode }));
    },
    [mode]
  );

  // AI Help — ask the backend to draft a reply the user can approve/edit
  const suggestReply = useCallback(async (): Promise<string> => {
    try {
      const res = await fetch(
        `${API_BASE}/api/suggest?user_id=${userId}&mode=${mode}`,
        { method: "POST" }
      );
      if (!res.ok) return "";
      const data = await res.json();
      return (data.suggestion || "").trim();
    } catch (e) {
      console.error("Suggest failed:", e);
      return "";
    }
  }, [userId, mode]);

  // Token balance — fetched on mount/user change and refreshed after spend/top-up.
  const refreshBalance = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/tokens?user_id=${userId}`);
      if (!res.ok) return;
      const data = await res.json();
      setBalance(data.balance ?? null);
    } catch (e) {
      console.error("Balance fetch failed:", e);
    }
  }, [userId]);

  // Spend tokens to reveal a blurred selfie. On success, flips that message to
  // unlocked and updates the balance. Returns the result so the caller can show
  // a "not enough tokens" hint on 402.
  const unlockPhoto = useCallback(
    async (photoUrl: string, messageId: string): Promise<UnlockResult> => {
      try {
        const res = await fetch(
          `${API_BASE}/api/unlock?user_id=${userId}&photo_url=${encodeURIComponent(photoUrl)}`,
          { method: "POST" }
        );
        const data = await res.json();
        if (!res.ok) {
          if (typeof data.balance === "number") setBalance(data.balance);
          return { ok: false, balance: data.balance ?? 0, error: data.error || "Unlock failed" };
        }
        setBalance(data.balance ?? null);
        setMessages((prev) =>
          prev.map((m) => (m.id === messageId ? { ...m, locked: false } : m))
        );
        return { ok: true, balance: data.balance ?? 0 };
      } catch (e) {
        console.error("Unlock failed:", e);
        return { ok: false, balance: 0, error: "Network error" };
      }
    },
    [userId]
  );

  // Demo "Get more" — grant a fresh batch of tokens.
  const topUp = useCallback(async (): Promise<void> => {
    try {
      const res = await fetch(`${API_BASE}/api/tokens/topup?user_id=${userId}`, {
        method: "POST",
      });
      if (!res.ok) return;
      const data = await res.json();
      setBalance(data.balance ?? null);
    } catch (e) {
      console.error("Top-up failed:", e);
    }
  }, [userId]);

  // Story heat meter — fetched on entering story mode and refreshed after each
  // story turn (the backend also pushes it over the socket).
  const refreshStoryHeat = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/story/progress?user_id=${userId}`);
      if (!res.ok) return;
      const data = await res.json();
      setStoryHeat(data);
    } catch (e) {
      console.error("Story progress fetch failed:", e);
    }
  }, [userId]);

  // Switch mode
  const switchMode = useCallback(
    (newMode: "sexting" | "story") => {
      setMode(newMode);
      setIsTyping(false);
      setIsWaitingStory(false);
      loadHistory(newMode);
      if (newMode === "story") refreshStoryHeat();
    },
    [loadHistory, refreshStoryHeat]
  );

  // Connect and load history. connect/loadHistory are memoised on the
  // connection identity (wsUrl/userId/userName) and userId respectively, so this
  // re-runs — reconnecting and reloading — whenever the user changes. Mode-driven
  // reloads are handled by switchMode, so `mode` is intentionally not a dep.
  useEffect(() => {
    connect();
    loadHistory(mode);
    refreshBalance();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connect, loadHistory, refreshBalance]);

  // Re-fetch the balance whenever the socket (re)connects. The initial mount
  // fetch can fail if the backend is momentarily down (e.g. a restart); without
  // this, the balance would stay stuck on "…" until a full page reload.
  useEffect(() => {
    if (isConnected) refreshBalance();
  }, [isConnected, refreshBalance]);

  // Keep the story meter current whenever the user is in story mode (initial
  // load and on reconnect).
  useEffect(() => {
    if (isConnected && mode === "story") refreshStoryHeat();
  }, [isConnected, mode, refreshStoryHeat]);

  return {
    messages,
    isTyping,
    isConnected,
    mode,
    isWaitingStory,
    balance,
    storyHeat,
    sendMessage,
    switchMode,
    suggestReply,
    triggerCard,
    unlockPhoto,
    topUp,
  };
}
