import React, { useState, useEffect } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';
import { Button } from '../../components/common/Button';

interface SessionData {
  id: string;
  creator_id: string;
  status: string;
  title: string;
  session_code: string;
  timeout_minutes: number;
  created_at: string;
}

export interface SessionDashboardProps {
  apiClient: WebApiClient;
  onEnterSession: (session: SessionData) => void;
  onLogout: () => void;
}

export const SessionDashboard: React.FC<SessionDashboardProps> = ({
  apiClient,
  onEnterSession,
  onLogout,
}) => {
  const [sessions, setSessions] = useState<SessionData[]>([]);
  const [loading, setLoading] = useState(false);
  const [joinCode, setJoinCode] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [timeoutMinutes, setTimeoutMinutes] = useState(30);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = async () => {
    try {
      setLoading(true);
      const data = await apiClient.get<SessionData[]>('/sessions/');
      setSessions(data);
    } catch (err) {
      console.error('Failed to list sessions', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleCreateSession = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const created = await apiClient.post<SessionData>('/sessions/', {
        title: newTitle || 'Assistance Workspace Session',
        timeout_minutes: timeoutMinutes,
      });
      onEnterSession(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Session creation failed');
    }
  };

  const handleJoinSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!joinCode) return;
    setError(null);
    try {
      const joined = await apiClient.post<SessionData>('/sessions/join', {
        session_code: joinCode.toUpperCase().trim(),
      });
      onEnterSession(joined);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid session code');
    }
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '2rem 1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2.5rem' }}>
        <div>
          <h1 style={{ fontSize: '2rem', marginBottom: '0.25rem' }}>Assistance Workspace</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Initiate, join, and manage remote assistance sessions
          </p>
        </div>
        <Button variant="secondary" onClick={onLogout}>
          Sign Out
        </Button>
      </div>

      {error && (
        <div style={{
          background: 'rgba(244, 63, 94, 0.15)',
          border: '1px solid var(--accent-rose)',
          padding: '0.85rem 1.25rem',
          borderRadius: 'var(--radius-md)',
          color: 'var(--accent-rose)',
          marginBottom: '1.5rem',
          fontSize: '0.9rem',
        }}>
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.75rem', marginBottom: '2.5rem' }}>
        {/* Quick Join Card */}
        <div className="glass-panel" style={{ padding: '1.75rem' }}>
          <h2 style={{ fontSize: '1.25rem', marginBottom: '0.75rem' }}>Join Live Session</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.25rem' }}>
            Enter the 6-character alphanumeric code provided by the helpee or primary helper.
          </p>
          <form onSubmit={handleJoinSession}>
            <div className="form-group">
              <input
                className="form-input"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '1.25rem',
                  letterSpacing: '0.2em',
                  textTransform: 'uppercase',
                  textAlign: 'center',
                }}
                placeholder="ABC123"
                maxLength={8}
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value)}
                required
              />
            </div>
            <Button type="submit" variant="primary" style={{ width: '100%' }}>
              Connect to Session
            </Button>
          </form>
        </div>

        {/* Create Session Card */}
        <div className="glass-panel" style={{ padding: '1.75rem' }}>
          <h2 style={{ fontSize: '1.25rem', marginBottom: '0.75rem' }}>Create New Session</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.25rem' }}>
            Launch a secure assistance room with real-time WebSockets signaling and E2EE.
          </p>
          <form onSubmit={handleCreateSession}>
            <div className="form-group">
              <label className="form-label">Session Title</label>
              <input
                className="form-input"
                placeholder="Troubleshooting Android Settings"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Timeout (Minutes)</label>
              <select
                className="form-input"
                value={timeoutMinutes}
                onChange={(e) => setTimeoutMinutes(Number(e.target.value))}
              >
                <option value={15}>15 Minutes</option>
                <option value={30}>30 Minutes</option>
                <option value={60}>60 Minutes</option>
              </select>
            </div>
            <Button type="submit" variant="primary" style={{ width: '100%' }}>
              Launch Session
            </Button>
          </form>
        </div>
      </div>

      {/* Active Sessions List */}
      <div className="glass-panel" style={{ padding: '1.75rem' }}>
        <h2 style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>Your Assistance Sessions</h2>
        {loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading session history...</p>
        ) : sessions.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            No active sessions found. Create or join a session above to get started.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {sessions.map((s) => (
              <div
                key={s.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '1rem 1.25rem',
                  background: 'var(--bg-glass)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-glass)',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: '1rem' }}>{s.title}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                    Code: <strong style={{ color: 'var(--accent-secondary)' }}>{s.session_code}</strong> &bull; Status: {s.status}
                  </div>
                </div>
                {s.status !== 'ended' ? (
                  <Button variant="primary" size="sm" onClick={() => onEnterSession(s)}>
                    Rejoin Room
                  </Button>
                ) : (
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Concluded</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
