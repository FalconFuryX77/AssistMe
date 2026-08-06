/**
 * Web Assistance Session Lifecycle Manager & WebSockets Signaling Router.
 */

export class WebSessionManager {
  private ws: WebSocket | null = null;
  private sessionId: string | null = null;
  private isConnected = false;

  public async connectToSession(sessionId: string, token: string, wsUrl: string): Promise<void> {
    this.sessionId = sessionId;
    const url = `${wsUrl}/ws/session/${sessionId}?token=${token}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.isConnected = true;
    };

    this.ws.onclose = () => {
      this.isConnected = false;
    };
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
  }
}
