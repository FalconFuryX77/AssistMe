import React, { useRef, useEffect } from 'react';

export interface DrawPoint {
  x: number;
  y: number;
}

export interface DrawingOverlayProps {
  strokes: DrawPoint[][];
  onStrokeComplete?: (points: DrawPoint[]) => void;
  onClear?: () => void;
}

export const DrawingOverlay: React.FC<DrawingOverlayProps> = ({ strokes, onStrokeComplete }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const currentStroke = useRef<DrawPoint[]>([]);
  const isDrawing = useRef(false);

  const render = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = 'rgba(16, 185, 129, 0.9)';
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    const draw = (pts: DrawPoint[]) => {
      if (pts.length < 2) {
        if (pts.length === 1) {
          ctx.beginPath();
          ctx.arc(pts[0].x, pts[0].y, 2, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(16, 185, 129, 0.9)';
          ctx.fill();
        }
        return;
      }
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i].x, pts[i].y);
      }
      ctx.stroke();
    };

    strokes.forEach(draw);
    draw(currentStroke.current);
  };

  useEffect(() => {
    render();
  }, [strokes]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const getPos = (e: PointerEvent): DrawPoint => {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const onDown = (e: PointerEvent) => {
      isDrawing.current = true;
      currentStroke.current = [getPos(e)];
      canvas.setPointerCapture(e.pointerId);
      render();
    };
    const onMove = (e: PointerEvent) => {
      if (!isDrawing.current) return;
      currentStroke.current.push(getPos(e));
      render();
    };
    const onUp = () => {
      if (!isDrawing.current) return;
      isDrawing.current = false;
      if (currentStroke.current.length > 0) {
        onStrokeComplete?.([...currentStroke.current]);
      }
      currentStroke.current = [];
    };

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointerleave', onUp);

    return () => {
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointerleave', onUp);
    };
  }, [onStrokeComplete]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        touchAction: 'none',
        cursor: 'crosshair',
        zIndex: 50,
      }}
    />
  );
};