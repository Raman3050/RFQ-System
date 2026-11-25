/**
 * One WebSocket per browser tab, shared by every page that wants live auction updates.
 *
 * - Authenticates with the in-memory access token as the first message (never in the URL).
 * - Reference-counted subscriptions: pages subscribe to the RFQ ids they show.
 * - Reconnects with exponential backoff + jitter and re-subscribes; on close code 4401
 *   (token expired) it refreshes the session first.
 * - Exposes a connection state so data hooks can fall back to polling when not live.
 */
import * as session from '@/features/auth/session';
import { syncServerTime } from '@/lib/serverTime';

export type LiveState = 'idle' | 'connecting' | 'live' | 'reconnecting';

export interface AuctionState {
  status: string;
  bid_start_at: string;
  current_close_at: string;
  forced_close_at: string;
  extension_count: number;
  current_lowest_bid: string | null;
}

export interface LiveMessage {
  type: string;
  rfq_id?: string;
  seq?: number | null;
  server_time?: string;
  auction?: AuctionState;
  extension?: {
    previous_close_at: string;
    new_close_at: string;
    reason: string;
    capped: boolean;
  } | null;
  rfq_ids?: string[];
}

type Handler = (msg: LiveMessage) => void;

const CLOSE_UNAUTHORIZED = 4401;
const IDLE_CLOSE_MS = 5_000;
const MAX_BACKOFF_MS = 30_000;

export class LiveClient {
  private ws: WebSocket | null = null;
  private state: LiveState = 'idle';
  private refs = new Map<string, number>();
  private handlers = new Set<Handler>();
  private stateListeners = new Set<() => void>();
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(private readonly url: () => string) {}

  // ---------------------------------------------------------------- public API

  getState = (): LiveState => this.state;

  isLive(): boolean {
    return this.state === 'live';
  }

  onStateChange(listener: () => void): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  onMessage(handler: Handler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  subscribe(ids: string[]): () => void {
    const added: string[] = [];
    for (const id of ids) {
      const n = this.refs.get(id) ?? 0;
      this.refs.set(id, n + 1);
      if (n === 0) added.push(id);
    }
    this.stopped = false;
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
    if (added.length && this.state === 'live') this.send({ type: 'subscribe', rfq_ids: added });
    this.ensureConnected();
    return () => this.release(ids);
  }

  /** Close the socket and forget subscriptions (e.g. on sign-out). */
  shutdown(): void {
    this.stopped = true;
    this.refs.clear();
    this.clearTimers();
    this.ws?.close(1000);
    this.ws = null;
    this.setState('idle');
  }

  // ---------------------------------------------------------------- internals

  private release(ids: string[]): void {
    const removed: string[] = [];
    for (const id of ids) {
      const n = (this.refs.get(id) ?? 1) - 1;
      if (n <= 0) {
        this.refs.delete(id);
        removed.push(id);
      } else this.refs.set(id, n);
    }
    if (removed.length && this.state === 'live')
      this.send({ type: 'unsubscribe', rfq_ids: removed });
    if (this.refs.size === 0 && !this.idleTimer) {
      // Keep the socket briefly so page-to-page navigation doesn't reconnect.
      this.idleTimer = setTimeout(() => {
        this.idleTimer = null;
        if (this.refs.size === 0) this.shutdown();
      }, IDLE_CLOSE_MS);
    }
  }

  private ensureConnected(): void {
    if (this.ws || this.reconnectTimer || this.stopped || this.refs.size === 0) return;
    void this.connect();
  }

  private async connect(): Promise<void> {
    this.setState(this.attempt ? 'reconnecting' : 'connecting');
    const token = session.getAccessToken() ?? (await session.refresh())?.access_token;
    if (!token || this.stopped) {
      this.setState('idle');
      return;
    }
    const ws = new WebSocket(this.url());
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
    ws.onmessage = (ev) => this.handle(String(ev.data));
    ws.onclose = (ev) => this.onClose(ws, ev.code);
    ws.onerror = () => undefined; // onclose follows and handles reconnection
  }

  private handle(raw: string): void {
    let msg: LiveMessage;
    try {
      msg = JSON.parse(raw) as LiveMessage;
    } catch {
      return;
    }
    if (msg.server_time) syncServerTime(msg.server_time);
    if (msg.type === 'READY') {
      this.attempt = 0;
      this.setState('live');
      if (this.refs.size) this.send({ type: 'subscribe', rfq_ids: [...this.refs.keys()] });
    }
    this.handlers.forEach((h) => h(msg));
  }

  private onClose(ws: WebSocket, code: number): void {
    if (this.ws !== ws) return; // an older socket
    this.ws = null;
    if (this.stopped || this.refs.size === 0) {
      this.setState('idle');
      return;
    }
    this.setState('reconnecting');
    if (code === CLOSE_UNAUTHORIZED) {
      // Access token expired: refresh, then reconnect straight away.
      void session.refresh().then((s) => {
        if (s) void this.connect();
        else this.shutdown();
      });
      return;
    }
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt);
    const delay = base / 2 + Math.random() * (base / 2);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }

  private send(msg: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private setState(state: LiveState): void {
    if (this.state === state) return;
    this.state = state;
    this.stateListeners.forEach((l) => l());
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.reconnectTimer = null;
    this.idleTimer = null;
    this.attempt = 0;
  }
}

export const liveClient = new LiveClient(
  () => `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`,
);

// Never keep a socket open for a signed-out user.
session.subscribe((s) => {
  if (!s) liveClient.shutdown();
});
