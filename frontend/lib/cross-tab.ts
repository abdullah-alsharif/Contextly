// Same-origin cross-tab notifications via BroadcastChannel; no-ops where the
// API is unavailable (private mode) — the sidebar's slow poll covers those.

export type CrossTabEvent = "conversations:updated" | "profile:updated";

const CHANNEL_NAME = "contextly-ui";

export function notifyCrossTab(event: CrossTabEvent): void {
  if (typeof BroadcastChannel === "undefined") return;
  try {
    new BroadcastChannel(CHANNEL_NAME).postMessage(event);
  } catch {
    // channel unavailable — the slow poll covers it
  }
}

export function subscribeCrossTab(event: CrossTabEvent, handler: () => void): () => void {
  if (typeof BroadcastChannel === "undefined") return () => {};
  try {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    const onMessage = (msg: MessageEvent) => {
      if (msg.data === event) handler();
    };
    channel.addEventListener("message", onMessage);
    return () => {
      channel.removeEventListener("message", onMessage);
      channel.close();
    };
  } catch {
    return () => {};
  }
}
