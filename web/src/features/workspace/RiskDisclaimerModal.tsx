import React from 'react';
import { Button } from '../../components/common/Button';

export interface RiskDisclaimerModalProps {
  disclaimerText: string;
  targetCapabilities: string[];
  onAccept: () => void;
  onDecline: () => void;
}

export const RiskDisclaimerModal: React.FC<RiskDisclaimerModalProps> = ({
  disclaimerText,
  targetCapabilities,
  onAccept,
  onDecline,
}) => {
  const [read, setRead] = React.useState(false);
  const [confirmed, setConfirmed] = React.useState(false);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.8)',
        backdropFilter: 'blur(10px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 130,
        padding: '1rem',
      }}
    >
      <div className="modal-content glass-panel" style={{ maxWidth: '520px', width: '100%', padding: '1.75rem' }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--accent-rose)', marginBottom: '0.5rem' }}>
          RISK DISCLAIMER
        </div>
        <h3 style={{ fontSize: '1.4rem', marginBottom: '0.75rem' }}>Request for more control</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '1rem' }}>
          Your helper is asking for these capabilities:
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1.25rem' }}>
          {targetCapabilities.map((cap) => (
            <span
              key={cap}
              style={{
                padding: '0.3rem 0.75rem',
                background: 'rgba(244, 63, 94, 0.15)',
                border: '1px solid var(--accent-rose)',
                borderRadius: '999px',
                fontSize: '0.85rem',
                color: 'var(--accent-rose)',
              }}
            >
              {cap}
            </span>
          ))}
        </div>
        <div
          style={{
            padding: '1rem',
            background: 'rgba(244, 63, 94, 0.08)',
            border: '1px solid var(--accent-rose)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            color: 'var(--text-secondary)',
            marginBottom: '1.25rem',
            maxHeight: '180px',
            overflowY: 'auto',
          }}
        >
          {disclaimerText || 'No disclaimer text provided by the helper.'}
        </div>
        <label style={{ display: 'flex', gap: '0.6rem', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem', cursor: 'pointer' }}>
          <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />
          I have read and understood the risks described above.
        </label>
        <label style={{ display: 'flex', gap: '0.6rem', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.75rem', cursor: 'pointer' }}>
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I explicitly authorize this helper to control these capabilities.
        </label>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <Button variant="primary" style={{ flex: 1 }} disabled={!read || !confirmed} onClick={onAccept}>
            Authorize Control
          </Button>
          <Button variant="secondary" style={{ flex: 1 }} onClick={onDecline}>
            Decline
          </Button>
        </div>
      </div>
    </div>
  );
};