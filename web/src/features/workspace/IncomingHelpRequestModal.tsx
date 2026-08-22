import React from 'react';
import { Button } from '../../components/common/Button';

export interface IncomingHelpRequestModalProps {
  onAccept: () => void;
  onDeny: () => void;
}

export const IncomingHelpRequestModal: React.FC<IncomingHelpRequestModalProps> = ({
  onAccept,
  onDeny,
}) => {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 120,
        padding: '1rem',
      }}
    >
      <div className="modal-content glass-panel" style={{ maxWidth: '420px', width: '100%', padding: '1.75rem' }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--accent-secondary)', marginBottom: '0.5rem' }}>
          INCOMING HELP REQUEST
        </div>
        <h3 style={{ fontSize: '1.4rem', marginBottom: '0.75rem' }}>Someone needs your help</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '1.75rem' }}>
          A trusted user is asking you to guide them. Accepting grants you overlay drawing
          (annotation) on their screen only. You can request more control later, which they
          must explicitly approve.
        </p>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <Button variant="primary" style={{ flex: 1 }} onClick={onAccept}>
            Accept & Guide
          </Button>
          <Button variant="danger" style={{ flex: 1 }} onClick={onDeny}>
            Deny
          </Button>
        </div>
      </div>
    </div>
  );
};