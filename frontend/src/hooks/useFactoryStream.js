import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiGet } from "../lib/api";

const STALL_AFTER_MS = 7000; // no stream event for this long -> fall back to polling
const POLL_EVERY_MS = 3000;

/**
 * Live factory snapshot.
 *
 * Primary path: Server-Sent Events (/api/stream) - the backend pushes a new
 * snapshot the moment data is stored (PostgreSQL NOTIFY), no polling.
 * Fallback: if the stream is silent for a few seconds (proxy that buffers SSE,
 * network blip) ONE 3-second timer polls /api/overview instead, and stops by
 * itself as soon as the stream delivers again. Everything is cleaned up on
 * unmount.
 */
export function useFactoryStream() {
  const [snapshot, setSnapshot] = useState(null);
  const [link, setLink] = useState("connecting"); // connecting | live | polling | offline
  const [error, setError] = useState("");
  const pollNow = useRef(() => {});

  useEffect(() => {
    let cancelled = false;
    let source = null;
    let controller = null;
    let lastEventAt = 0;
    let polling = false;
    const startedAt = Date.now();

    const accept = (data, via) => {
      if (cancelled) return;
      setSnapshot(data);
      setLink(via);
      setError("");
    };

    const poll = async () => {
      if (cancelled || polling) return;
      polling = true;
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const data = await apiGet("/api/overview", controller.signal);
        const streamHealthy = Date.now() - lastEventAt < STALL_AFTER_MS;
        // The very first fetch lands before the stream handshake: don't label
        // that "polling" - only report polling once the stream has really stalled.
        const early = Date.now() - startedAt < STALL_AFTER_MS;
        accept(data, streamHealthy ? "live" : early ? "connecting" : "polling");
      } catch (pollError) {
        if (!cancelled) {
          setLink("offline");
          setError(`Cannot reach the API (${pollError.message}). Retrying automatically.`);
        }
      } finally {
        clearTimeout(timeout);
        polling = false;
      }
    };
    pollNow.current = poll;

    const connect = () => {
      if (typeof EventSource === "undefined") return;
      source = new EventSource(`${API_BASE}/api/stream`);
      source.addEventListener("snapshot", (event) => {
        lastEventAt = Date.now();
        try {
          accept(JSON.parse(event.data), "live");
        } catch {
          // ignore a malformed event; the next one replaces it
        }
      });
      source.addEventListener("error", (event) => {
        // Server-sent "error" events carry data; connection errors do not.
        if (event.data) setError("The API reported a database problem. Retrying...");
      });
      // On a dropped connection EventSource reconnects by itself.
    };

    connect();
    // The single watchdog timer: polls only while the stream is silent.
    const watchdog = setInterval(() => {
      if (Date.now() - lastEventAt > STALL_AFTER_MS) poll();
    }, POLL_EVERY_MS);
    poll(); // first paint doesn't wait for the stream handshake

    return () => {
      cancelled = true;
      clearInterval(watchdog);
      if (source) source.close();
      if (controller) controller.abort();
    };
  }, []);

  const refresh = useCallback(() => pollNow.current(), []);
  return { snapshot, link, error, refresh };
}
