import React, { useRef, useEffect, useState, useCallback } from 'react';
import { CanvasRenderer } from '../../core/graphics/canvas_renderer';
import { WebApiClient } from '../../core/network/web_api_client';

export interface RemoteCanvasViewportProps {
  sessionId: string;
  apiClient: WebApiClient;
  canvasRenderer: CanvasRenderer;
  isFlagSecureActive?: boolean;
  isScreenSharing?: boolean;
}

export const RemoteCanvasViewport: React.FC<RemoteCanvasViewportProps> = ({
  sessionId,
  apiClient,
  canvasRenderer,
  isFlagSecureActive = false,
  isScreenSharing = true,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (canvasRef.current) {
      canvasRenderer.attachCanvas(canvasRef.current);
    }
  }, [canvasRenderer]);

  // Handle Video Frame Render Loop
  useEffect(() => {
    let animationId: number;
    const renderLoop = () => {
      if (videoRef.current && canvasRef.current) {
        canvasRenderer.renderFrame(videoRef.current);
      }
      animationId = requestAnimationFrame(renderLoop);
    };
    animationId = requestAnimationFrame(renderLoop);

    return () => {
      cancelAnimationFrame(animationId);
      canvasRenderer.stop();
    };
  }, [canvasRenderer]);

  // Translate click to normalized coordinates and dispatch remote input
  const handleCanvasClick = useCallback(
    async (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!canvasRef.current) return;
      const rect = canvasRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      canvasRenderer.updateCursorPosition(x, y, true);

      try {
        await apiClient.post(`/sessions/${sessionId}/remote-control/input`, {
          event_type: 'tap',
          x: x * 1080,
          y: y * 1920,
          normalized_x: x,
          normalized_y: y,
        });
      } catch (err) {
        console.warn('Remote control input dispatch notice:', err);
      }
    },
    [apiClient, canvasRenderer, sessionId]
  );

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    setDragStart({
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    });
    setIsDragging(true);
  };

  const handleMouseUp = async (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDragging || !dragStart || !canvasRef.current) return;
    setIsDragging(false);

    const rect = canvasRef.current.getBoundingClientRect();
    const endX = (e.clientX - rect.left) / rect.width;
    const endY = (e.clientY - rect.top) / rect.height;

    // Check if drag occurred
    const dist = Math.hypot(endX - dragStart.x, endY - dragStart.y);
    if (dist > 0.02) {
      try {
        await apiClient.post(`/sessions/${sessionId}/remote-control/input`, {
          event_type: 'drag',
          x: dragStart.x * 1080,
          y: dragStart.y * 1920,
          end_x: endX * 1080,
          end_y: endY * 1920,
          duration_ms: 300,
        });
      } catch (err) {
        console.warn('Drag input dispatch notice:', err);
      }
    }
  };

  return (
    <div className="canvas-viewport-container">
      {/* Hidden WebRTC video element for stream decoding */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        style={{ display: 'none' }}
      />

      {/* Render Canvas */}
      <canvas
        ref={canvasRef}
        className="canvas-viewport"
        width={1920}
        height={1080}
        onClick={handleCanvasClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
      />

      {/* Sensitive Window / FLAG_SECURE Overlay */}
      {isFlagSecureActive && (
        <div className="canvas-flag-secure-overlay">
          <div style={{ fontSize: '2rem' }}>🔒</div>
          <div style={{ fontWeight: 700, fontSize: '1.2rem' }}>Sensitive Screen Protected</div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            The remote user opened a password prompt, banking app, or FLAG_SECURE window.
          </div>
        </div>
      )}

      {/* Waiting for Stream Placeholder */}
      {!isScreenSharing && !isFlagSecureActive && (
        <div style={{
          position: 'absolute',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.75rem',
          color: 'var(--text-secondary)',
        }}>
          <div style={{ fontSize: '2rem' }}>📱</div>
          <div style={{ fontWeight: 600 }}>Waiting for Helpee Screen Sharing Stream...</div>
        </div>
      )}
    </div>
  );
};
