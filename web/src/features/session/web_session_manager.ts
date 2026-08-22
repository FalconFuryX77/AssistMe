/**
 * Web Assistance Session Lifecycle Manager & WebSockets Signaling Router.
 */

export type SessionEvent = { type: string; [key: string]: unknown };

export class WebSessionManager {
  private ws: WebSocket | null = null;
  private sessionId: string | null = null;
  private isConnected = false;
  private listeners: Array<(event: SessionEvent) => void> = [];

  public async connectToSession(sessionId: string, token: string, wsUrl: string): Promise<void> {
    this.sessionId = sessionId;
    const url = `${wsUrl}/ws/session/${sessionId}?token=${token}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.isConnected = true;
    };

    this.ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as SessionEvent;
        this.listeners.forEach((fn) => fn(event));
      } catch {
        // Ignore malformed frames
      }
    };

    this.ws.onclose = () => {
      this.isConnected = false;
    };
  }

  public onEvent(listener: (event: SessionEvent) => void): void {
    this.listeners.push(listener);
  }

  public sendSignal(type: string, payload: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...payload }));
    }
  }

  public disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.isConnected = false;
    this.listeners = [];
  }
}