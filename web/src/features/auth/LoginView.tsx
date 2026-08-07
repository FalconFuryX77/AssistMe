import React, { useState } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';
import { WebAuthStore } from '../../core/security/web_auth_store';
import { Button } from '../../components/common/Button';

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface LoginViewProps {
  apiClient: WebApiClient;
  authStore: WebAuthStore;
  onLoginSuccess: () => void;
  onNavigateToRegister: () => void;
}

export const LoginView: React.FC<LoginViewProps> = ({
  apiClient,
  authStore,
  onLoginSuccess,
  onNavigateToRegister,
}) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMessage(null);

    try {
      const resp = await apiClient.post<LoginResponse>(
        '/auth/login',
        { email, password },
        false
      );

      authStore.saveTokens(resp.access_token, resp.refresh_token);
      onLoginSuccess();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '80vh',
      padding: '1.5rem',
    }}>
      <div className="glass-panel" style={{ width: '100%', maxWidth: '440px', padding: '2.5rem' }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
            <span className="logo-badge">ACSAF</span>
            <h1 style={{ fontSize: '1.75rem' }}>AssistMe</h1>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Adaptive Context-Aware Remote Assistance
          </p>
        </div>

        {errorMessage && (
          <div style={{
            background: 'rgba(244, 63, 94, 0.15)',
            border: '1px solid var(--accent-rose)',
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-md)',
            color: 'var(--accent-rose)',
            marginBottom: '1.25rem',
            fontSize: '0.85rem',
          }}>
            {errorMessage}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="email-input">Email Address</label>
            <input
              id="email-input"
              className="form-input"
              type="email"
              placeholder="helper@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="password-input">Password</label>
            <input
              id="password-input"
              className="form-input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <Button
            type="submit"
            variant="primary"
            loading={loading}
            style={{ width: '100%', marginTop: '0.5rem', padding: '0.85rem' }}
          >
            Sign In to Workspace
          </Button>
        </form>

        <div style={{ marginTop: '1.5rem', textAlign: 'center', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Don't have an account?{' '}
          <button
            onClick={onNavigateToRegister}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent-primary)',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Register
          </button>
        </div>
      </div>
    </div>
  );
};
