import React, { useEffect, useState, useCallback } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';
import { WebSessionManager, SessionEvent } from '../session/web_session_manager';
import { IncomingHelpRequestModal } from './IncomingHelpRequestModal';
import { RiskDisclaimerModal } from './RiskDisclaimerModal';
import { DrawingOverlay, DrawPoint } from './DrawingOverlay';

export interface AssistanceCoordinatorProps {
  sessionId: string;
  apiClient: WebApiClient;
  sessionManager: WebSessionManager;
  isHelpee: boolean;
  helperDeviceFingerprint: string;
}

interface PendingEscalation {
  id: string;
  disclaimer_text: string;
  target_capabilities: string[];
}

export const AssistanceCoordinator: React.FC<AssistanceCoordinatorProps> = ({
  sessionId,
  apiClient,
  sessionManager,
  isHelpee,
  helperDeviceFingerprint,
}) => {
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null);
  const [pendingEscalation, setPendingEscalation] = useState<PendingEscalation | null>(null);
  const [strokes, setStrokes] = useState<DrawPoint[][]>([]);
  const [isRequestingHelp, setIsRequestingHelp] = useState(false);
  const [showEscalationMenu, setShowEscalationMenu] = useState(false);

  const onEvent = useCallback((event: SessionEvent) => {
    switch (event.type) {
      case 'assistance_requested': {
        const requestId = event.request_id;
        if (requestId && typeof requestId === 'string') {
          setPendingRequestId(requestId);
        }
        break;
      }
      case 'escalation_requested': {
        const id = event.escalation_id;
        if (id && typeof id === 'string') {
          setPendingEscalation({
            id,
            disclaimer_text: String(event.disclaimer_text ?? ''),
            target_capabilities: Array.isArray(event.target_capabilities)
              ? (event.target_capabilities as string[])
              : [],
          });
        }
        break;
      }
      case 'escalation_responded': {
        if (event.status === 'approved') {
          // Control granted to the helper.
        }
        break;
      }
      case 'draw_stroke': {
        const raw = event.points;
        if (Array.isArray(raw)) {
          const pts = (raw as Array<{ x: number; y: number }>).map((p) => ({
            x: Number(p.x),
            y: Number(p.y),
          }));
          setStrokes((prev) => [...prev, pts]);
        }
        break;
      }
      case 'draw_clear': {
        setStrokes([]);
        break;
      }
    }
  }, []);

  useEffect(() => {
    sessionManager.onEvent(onEvent);
    return () => {
      // WebSessionManager.disconnect clears listeners; nothing else needed here.
    };
  }, [sessionManager, onEvent]);

  const handleRequestHelp = async () => {
    if (isRequestingHelp) return;

    // Load trusted devices so the helpee can pick the helper's device.
    let trusted: Array<{ device_fingerprint: string; friendly_name: string | null }> = [];
    try {
      const data = await apiClient.listTrustedDevices() as unknown as {
        devices: Array<{ device_fingerprint: string; friendly_name: string | null }>;
      };
      trusted = data.devices ?? [];
    } catch {
      // fall through
    }

    const helperUserId = window.prompt('Enter the helper user id:');
    if (!helperUserId || !helperUserId.trim()) return;

    let helperFingerprint = '';
    if (trusted.length === 1) {
      helperFingerprint = trusted[0].device_fingerprint;
    } else if (trusted.length > 1) {
      const pick = window.prompt(
        `This device is the HELPEE — pick which trusted helper device to request from:\n\n${trusted
          .map((d, i) => `${i + 1}. ${d.friendly_name ?? d.device_fingerprint.slice(0, 16)}`)
          .join('\n')}\n\nEnter the number:`,
      );
      const idx = Number((pick ?? '').trim()) - 1;
      if (!Number.isInteger(idx) || idx < 0 || idx >= trusted.length) {
        window.alert('Invalid selection.');
        return;
      }
      helperFingerprint = trusted[idx].device_fingerprint;
    } else {
      const manual = window.prompt(
        'No trusted devices found. Paste the helper\'s Device ID (the one you paired in Trusted Devices):',
      );
      if (!manual || !manual.trim()) {
        window.alert('A helper Device ID is required.');
        return;
      }
      helperFingerprint = manual.trim();
    }

    setIsRequestingHelp(true);
    try {
      const req = await apiClient.requestHelp(
        sessionId,
        helperUserId.trim(),
        helperFingerprint
      ) as unknown as { id: string };
      sessionManager.sendSignal('assistance_requested', {
        request_id: req.id,
        helper_user_id: helperUserId.trim(),
        helpee_user_id: helperUserId.trim(),
      });
    } catch (err) {
      window.alert(`Request failed: ${err instanceof Error ? err.message : err}`);
    } finally {
      setIsRequestingHelp(false);
    }
  };

  const handleRespondToRequest = async (accept: boolean) => {
    if (!pendingRequestId) return;
    const id = pendingRequestId;
    setPendingRequestId(null);
    try {
      await apiClient.respondToHelpRequest(sessionId, id, accept, helperDeviceFingerprint);
      if (accept) {
        sessionManager.sendSignal('assistance_request_responded', { request_id: id, status: 'accepted' });
      }
    } catch (err) {
      window.alert(`Response failed: ${err instanceof Error ? err.message : err}`);
    }
  };

  const handleRequestEscalation = async (caps: string[]) => {
    setShowEscalationMenu(false);
    try {
      const esc = await apiClient.requestEscalation(sessionId, caps) as unknown as {
        id: string;
        disclaimer_text: string;
      };
      sessionManager.sendSignal('escalation_requested', {
        escalation_id: esc.id,
        target_capabilities: caps,
        disclaimer_text: esc.disclaimer_text,
      });
    } catch (err) {
      window.alert(`Escalation request failed: ${err instanceof Error ? err.message : err}`);
    }
  };

  const handleRespondToEscalation = async (accept: boolean) => {
    if (!pendingEscalation) return;
    const esc = pendingEscalation;
    setPendingEscalation(null);
    try {
      const result = await apiClient.respondToEscalation(sessionId, esc.id, accept, accept) as unknown as {
        status: string;
      };
      if (accept && result.status === 'approved') {
        sessionManager.sendSignal('escalation_responded', { escalation_id: esc.id, status: 'approved' });
      }
    } catch (err) {
      window.alert(`Escalation response failed: ${err instanceof Error ? err.message : err}`);
    }
  };

  const handleStrokeComplete = useCallback((pts: DrawPoint[]) => {
    setStrokes((prev) => [...prev, pts]);
    sessionManager.sendSignal('draw_stroke', { points: pts });
  }, [sessionManager]);

  return (
    <>
      {/* Drawing overlay — interactive for helpers, passive display for helpees */}
      <DrawingOverlay
        strokes={strokes}
        onStrokeComplete={isHelpee ? undefined : handleStrokeComplete}
      />

      {/* Helper: incoming help request popup */}
      {!isHelpee && pendingRequestId && (
        <IncomingHelpRequestModal
          onAccept={() => handleRespondToRequest(true)}
          onDeny={() => handleRespondToRequest(false)}
        />
      )}

      {/* Helpee: escalation risk disclaimer popup */}
      {isHelpee && pendingEscalation && (
        <RiskDisclaimerModal
          disclaimerText={pendingEscalation.disclaimer_text}
          targetCapabilities={pendingEscalation.target_capabilities}
          onAccept={() => handleRespondToEscalation(true)}
          onDecline={() => handleRespondToEscalation(false)}
        />
      )}

      {/* Helpee: one-click request-help button */}
      {isHelpee && (
        <div style={{ position: 'fixed', bottom: '5.5rem', right: '1.5rem', zIndex: 60 }}>
          <button
            className="btn btn-primary"
            style={{ borderRadius: '999px', padding: '0.75rem 1.5rem', boxShadow: '0 4px 16px rgba(0,0,0,0.3)' }}
            onClick={handleRequestHelp}
            disabled={isRequestingHelp}
          >
            {isRequestingHelp ? 'Sending...' : '🆘 Request Help'}
          </button>
        </div>
      )}

      {/* Helper: request more control button */}
      {!isHelpee && (
        <div style={{ position: 'fixed', bottom: '5.5rem', right: '1.5rem', zIndex: 60 }}>
          <button
            className="btn btn-secondary"
            style={{ borderRadius: '999px', padding: '0.75rem 1.5rem' }}
            onClick={() => setShowEscalationMenu((v) => !v)}
          >
            ⛶ Request More Control
          </button>
          {showEscalationMenu && (
            <div
              className="glass-panel"
              style={{
                position: 'absolute',
                bottom: '3rem',
                right: 0,
                padding: '1rem',
                width: '260px',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem',
              }}
            >
              {['tap', 'drag', 'pointer'].map((cap) => (
                <button key={cap} className="btn btn-secondary" onClick={() => handleRequestEscalation([cap])}>
                  Request: {cap}
                </button>
              ))}
              <button className="btn btn-secondary" onClick={() => handleRequestEscalation(['tap', 'drag', 'pointer'])}>
                Request: full control
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
};