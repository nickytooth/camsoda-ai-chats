"use client";

import { useState, useRef, useCallback, useEffect } from "react";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  mode: "sexting" | "story";
}

interface UseChatOptions {
  wsUrl?: string;
  userId?: number;
  userName?: string;
}

export function useChat({ wsUrl = "ws://localhost:8000/ws/chat", userId = 1, userName = "" }: UseChatOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [mode, setMode] = useState<"sexting" | "story">("sexting");
  const [isConnected, setIsConnected] = useState(false);
  const [isWaitingStory, setIsWaitingStory] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const idCounter = useRef(0);
  const openingAnimating = useRef(false);

  const genId = () => `msg-${Date.now()}-${idCounter.current++}`;

  // Load history for current mode
  const loadHistory = useCallback(async (m: string) => {
    try {
      const res = await fetch(`http://localhost:8000/api/history/${m}?user_id=${userId}`);
      if (!res.ok) return;
      const data = await res.json();
      const loaded: ChatMessage[] = (data.messages || []).map((msg: any) => ({
        id: genId(),
        role: msg.role,
        content: msg.content,
        timestamp: msg.timestamp,
        mode: m,
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
        openingAnimating.current = true;
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
  }, []);

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
          const imgMsg: ChatMessage = {
            id: genId(),
            role: "assistant",
            content: `[image:${data.url}]`,
            timestamp: data.timestamp || Date.now() / 1000,
            mode: data.mode || "sexting",
          };
          setMessages((prev) => [...prev, imgMsg]);
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
  }, [wsUrl, userId]);

  // Send message
  const sendMessage = useCallback(
    (text: string, imageBase64?: string) => {
      if (!text.trim() && !imageBase64) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      // Add user message to UI immediately
      const userMsg: ChatMessage = {
        id: genId(),
        role: "user",
        content: text,
        timestamp: Date.now() / 1000,
        mode,
      };
      setMessages((prev) => [...prev, userMsg]);

      if (mode === "story") {
        setIsWaitingStory(true);
      }

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

  // AI Help — ask the backend to draft a reply the user can approve/edit
  const suggestReply = useCallback(async (): Promise<string> => {
    try {
      const res = await fetch(
        `http://localhost:8000/api/suggest?user_id=${userId}&mode=${mode}`,
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

  // Switch mode
  const switchMode = useCallback(
    (newMode: "sexting" | "story") => {
      setMode(newMode);
      setIsTyping(false);
      setIsWaitingStory(false);
      loadHistory(newMode);
    },
    [loadHistory]
  );

  // Connect on mount (reconnect when userId changes)
  useEffect(() => {
    connect();
    loadHistory(mode);
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [userId]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    messages,
    isTyping,
    isConnected,
    mode,
    isWaitingStory,
    sendMessage,
    switchMode,
    suggestReply,
  };
}
