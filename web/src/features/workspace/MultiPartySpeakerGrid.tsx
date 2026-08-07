import React, { useState } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';
import { Button } from '../../components/common/Button';
import { Modal } from '../../components/common/Modal';

export interface ParticipantItem {
  id: string;
  user_id: string;
  role: 'primary_helper' | 'secondary_helper' | 'observer' | 'helpee';
  status: string;
  is_active_speaker?: boolean;
  email?: string;
}

export interface MultiPartySpeakerGridProps {
  sessionId: string;
  apiClient: WebApiClient;
  participants: ParticipantItem[];
  isCreator: boolean;
  onRefreshParticipants: () => void;
}

export const MultiPartySpeakerGrid: React.FC<MultiPartySpeakerGridProps> = ({
  sessionId,
  apiClient,
  participants,
  isCreator,
  onRefreshParticipants,
}) => {
  const [isInviteOpen, setIsInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'secondary_helper' | 'observer'>('secondary_helper');
  const [loading, setLoading] = useState(false);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await apiClient.post(`/sessions/${sessionId}/participants/invite`, {
        email_or_user_id: inviteEmail.trim(),
        role: inviteRole,
      });
      setIsInviteOpen(false);
      setInviteEmail('');
      onRefreshParticipants();
    } catch (err) {
      console.warn('Invite participant error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleRoleChange = async (userId: string, role: string) => {
    try {
      await apiClient.patch(`/sessions/${sessionId}/participants/${userId}/role`, {
        role,
      });
      onRefreshParticipants();
    } catch (err) {
      console.warn('Update role notice:', err);
    }
  };

  return (
    <div style={{ marginTop: '1.25rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>
          Session Participants ({participants.length})
        </h3>
        {isCreator && (
          <Button variant="secondary" size="sm" onClick={() => setIsInviteOpen(true)}>
            + Invite Helper
          </Button>
        )}
      </div>

      <div className="participant-grid">
        {participants.map((p) => {
          const roleColor =
            p.role === 'primary_helper'
              ? 'var(--accent-primary)'
              : p.role === 'secondary_helper'
              ? 'var(--accent-secondary)'
              : p.role === 'helpee'
              ? 'var(--accent-emerald)'
              : 'var(--text-muted)';

          return (
            <div
              key={p.id}
              className={`participant-card ${p.is_active_speaker ? 'active-speaker' : ''}`}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <span className="badge-role" style={{ color: roleColor }}>
                  {p.role.replace('_', ' ')}
                </span>
                {p.is_active_speaker && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--accent-emerald)' }}>
                    🔊 Speaking
                  </span>
                )}
              </div>

              <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.25rem' }}>
                {p.email || `User ${p.user_id.slice(0, 8)}`}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                Status: {p.status}
              </div>

              {/* Creator RBAC Controls */}
              {isCreator && p.role !== 'helpee' && p.role !== 'primary_helper' && (
                <div style={{ marginTop: '0.75rem' }}>
                  <select
                    className="form-input"
                    style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                    value={p.role}
                    onChange={(e) => handleRoleChange(p.user_id, e.target.value)}
                  >
                    <option value="secondary_helper">Secondary Helper</option>
                    <option value="observer">Observer (Read-Only)</option>
                  </select>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Invite Modal */}
      <Modal
        isOpen={isInviteOpen}
        onClose={() => setIsInviteOpen(false)}
        title="Invite Additional Helper or Observer"
      >
        <form onSubmit={handleInvite}>
          <div className="form-group">
            <label className="form-label">Email or User ID</label>
            <input
              className="form-input"
              type="text"
              placeholder="helper2@example.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">Participant Role</label>
            <select
              className="form-input"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as any)}
            >
              <option value="secondary_helper">Secondary Helper (Control & Voice)</option>
              <option value="observer">Observer (View Only)</option>
            </select>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.25rem' }}>
            <Button variant="secondary" onClick={() => setIsInviteOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={loading}>
              Send Invitation
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
