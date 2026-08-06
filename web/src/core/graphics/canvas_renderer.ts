/**
 * High-Performance HTML5 Canvas Remote Screen & Video Frame Renderer.
 * Renders remote screen share video streams with scaling, scaling math, and remote cursor overlays.
 */

export interface RemoteCursorPosition {
  x: number;
  y: number;
  visible: boolean;
}

export class CanvasRenderer {
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private animationFrameId: number | null = null;
  private currentCursor: RemoteCursorPosition = { x: 0, y: 0, visible: false };

  public attachCanvas(canvasElement: HTMLCanvasElement): void {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');
  }

  public updateCursorPosition(x: number, y: number, visible = true): void {
    this.currentCursor = { x, y, visible };
  }

  public renderFrame(videoElement: HTMLVideoElement): void {
    if (!this.canvas || !this.ctx) return;

    const width = this.canvas.width;
    const height = this.canvas.height;

    // Clear background
    this.ctx.fillStyle = '#000000';
    this.ctx.fillRect(0, 0, width, height);

    // Draw video frame
    try {
      this.ctx.drawImage(videoElement, 0, 0, width, height);
    } catch {
      // Ignored if video frame not ready yet
    }

    // Overlay Remote Cursor Pointer
    if (this.currentCursor.visible) {
      this.ctx.beginPath();
      this.ctx.arc(this.currentCursor.x * width, this.currentCursor.y * height, 8, 0, 2 * Math.PI);
      this.ctx.fillStyle = 'rgba(255, 0, 0, 0.8)';
      this.ctx.fill();
      this.ctx.lineWidth = 2;
      this.ctx.strokeStyle = '#FFFFFF';
      this.ctx.stroke();
    }
  }

  public stop(): void {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
  }
}
