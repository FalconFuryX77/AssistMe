import React, { useState } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';
import { Modal } from '../../components/common/Modal';
import { Button } from '../../components/common/Button';

export interface SecurityZeroizeModalProps {
  isOpen: boolean;
  onClose: () => void;
  sessionId: string;
  apiClient: WebApiClient;
  fingerprint?: string;
  isMitmVerified?: boolean;
  onZeroized: () => void;
}

export const SecurityZeroizeModal: React.FC<SecurityZeroizeModalProps> = ({
  isOpen,
  onClose,
  sessionId,
  apiClient,
  fingerprint,
  isMitmVerified = false,
  onZeroized,
}) => {
  const [zeroizing, setZeroizing] = useState(false);
  const [iceRestarting, setIceRestarting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const handleZeroizeKeys = async () => {
    setZeroizing(true);
    setStatusMessage(null);
    try {
      await apiClient.post(`/sessions/${sessionId}/security/zeroize`);
      setStatusMessage('Cryptographic memory scrub complete. In-memory Double Ratchet keys wiped.');
      onZeroized();
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'Zeroization failed');
    } finally {
      setZeroizing(false);
    }
  };

  const handleIceRestart = async () => {
    setIceRestarting(true);
    setStatusMessage(null);
    try {
      await apiClient.post(`/sessions/${sessionId}/ice-restart`, {
        reason: 'manual_recovery_requested',
      });
      setStatusMessage('ICE restart credentials requested. Connection recovery active.');
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'ICE restart failed');
    } finally {
      setIceRestarting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="E2EE Security & Hardening Controls"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {/* SAS Safety Number Fingerprint */}
        <div style={{
          padding: '1rem',
          background: 'var(--bg-glass)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-glass)',
        }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Signal Protocol SAS Safety Number
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '1.1rem',
            letterSpacing: '0.15em',
            color: 'var(--accent-emerald)',
            background: 'rgba(0, 0, 0, 0.4)',
            padding: '0.65rem 1rem',
            borderRadius: 'var(--radius-sm)',
            textAlign: 'center',
          }}>
            {fingerprint || 'e2ee_sas_verified_sha256'}
          </div>
          <div style={{ fontSize: '0.75rem', color: isMitmVerified ? 'var(--accent-emerald)' : 'var(--accent-amber)', marginTop: '0.5rem' }}>
            {isMitmVerified ? '✓ MITM Verified — No eavesdropping detected.' : '⚠️ Unverified fingerprint — compare numbers with helpee.'}
          </div>
        </div>

        {statusMessage && (
          <div style={{
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.85rem',
            background: 'rgba(99, 102, 241, 0.15)',
            border: '1px solid var(--accent-primary)',
            color: 'var(--text-primary)',
          }}>
            {statusMessage}
          </div>
        )}

        {/* Action Buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <Button
            variant="secondary"
            loading={iceRestarting}
            onClick={handleIceRestart}
          >
            🔄 Trigger WebRTC Connection Recovery (ICE Restart)
          </Button>

          <Button
            variant="danger"
            loading={zeroizing}
            onClick={handleZeroizeKeys}
          >
            🛑 Zeroize & Scrub Cryptographic Memory
          </Button>
        </div>
      </div>
    </Modal>
  );
};
