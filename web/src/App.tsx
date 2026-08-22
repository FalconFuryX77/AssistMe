import React, { useState, useEffect, useMemo } from 'react';
import { WebAuthStore } from './core/security/web_auth_store';
import { WebApiClient } from './core/network/web_api_client';
import { CanvasRenderer } from './core/graphics/canvas_renderer';
import { WebSessionManager } from './features/session/web_session_manager';
import { getBrowserFingerprint } from './core/security/browser_device_identity';
import { LoginView } from './features/auth/LoginView';
import { RegisterView } from './features/auth/RegisterView';
import { SessionDashboard } from './features/dashboard/SessionDashboard';
import { RemoteCanvasViewport } from './features/workspace/RemoteCanvasViewport';
import { VoiceControlBar } from './features/workspace/VoiceControlBar';
import { ChatFileDrawer, ChatMessageItem } from './features/workspace/ChatFileDrawer';
import { MultiPartySpeakerGrid, ParticipantItem } from './features/workspace/MultiPartySpeakerGrid';
import { SecurityZeroizeModal } from './features/workspace/SecurityZeroizeModal';
import { AssistanceCoordinator } from './features/workspace/AssistanceCoordinator';
import { TrustedDevicesView } from './features/devices/TrustedDevicesView';
import { ToastContainer, ToastMessage } from './components/common/Toast';
import './styles/theme.css';

// Resolve the backend address from where the page itself was served.
// Works from any device on the network: open http://<pc-ip>:5173 and the app
// automatically talks to http://<pc-ip>:8000. Override with VITE_API_BASE_URL.
const detectApiBase = (): string => {
  const override = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (override) return override;
  const host = window.location.hostname;
  return `http://${host}:8000`;
};

const detectWsBase = (): string => {
  const override = import.meta.env.VITE_WS_BASE_URL as string | undefined;
  if (override) return override;
  const host = window.location.hostname;
  return `ws://${host}:8000`;
};

const API_BASE_URL = detectApiBase();
const WS_BASE_URL = detectWsBase();

export const App: React.FC = () => {
  const authStore = useMemo(() => new WebAuthStore(), []);
  const apiClient = useMemo(() => new WebApiClient(API_BASE_URL, authStore), [authStore]);
  const canvasRenderer = useMemo(() => new CanvasRenderer(), []);
  const sessionManager = useMemo(() => new WebSessionManager(), []);

  const deviceFingerprint = useMemo(() => getBrowserFingerprint(), []);

  const [view, setView] = useState<'login' | 'register' | 'dashboard' | 'workspace' | 'trusted-devices'>('login');
  const [activeSession, setActiveSession] = useState<any | null>(null);
  const [isSecurityModalOpen, setIsSecurityModalOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [participants, setParticipants] = useState<ParticipantItem[]>([]);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [isFlagSecure, setIsFlagSecure] = useState(false);
  const [isHelpee, setIsHelpee] = useState(false);

  // Check existing token on launch
  useEffect(() => {
    const token = authStore.getAccessToken();
    if (token) {
      setView('dashboard');
    }
  }, [authStore]);

  const addToast = (type: 'info' | 'success' | 'warning' | 'error', title: string, message?: string) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, type, title, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  const handleEnterSession = async (session: any, isHelpeeRole = false) => {
    setActiveSession(session);
    setIsHelpee(isHelpeeRole);
    setView('workspace');

    const token = authStore.getAccessToken();
    if (token) {
      await sessionManager.connectToSession(session.id, token, WS_BASE_URL);
      addToast('success', 'Connected to Session', `Room: ${session.session_code}`);
    }
  };

  const handleLeaveSession = async () => {
    if (activeSession) {
      try {
        await apiClient.post(`/sessions/${activeSession.id}/leave`);
      } catch {
        // Ignored
      }
      sessionManager.disconnect();
      setActiveSession(null);
      setView('dashboard');
      addToast('info', 'Left Assistance Session');
    }
  };

  const handleSendMessage = async (content: string, isEncrypted = false) => {
    if (!activeSession) return;
    try {
      const sent = await apiClient.post<ChatMessageItem>(`/sessions/${activeSession.id}/chat/messages`, {
        content,
        is_encrypted: isEncrypted,
      });
      setMessages((prev) => [...prev, sent]);
    } catch (err) {
      console.warn('Send message error:', err);
    }
  };

  const handleLogout = () => {
    authStore.clearTokens();
    sessionManager.disconnect();
    setActiveSession(null);
    setView('login');
  };

  return (
    <div>
      {/* App Navigation Bar */}
      <header className="app-header">
        <div className="logo-container">
          <span className="logo-badge">ACSAF</span>
          <span>AssistMe Workspace</span>
        </div>
        {view === 'workspace' && activeSession && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Role: <strong style={{ color: 'var(--accent-secondary)' }}>{isHelpee ? 'Helpee' : 'Helper'}</strong>
            </span>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setIsHelpee((v) => !v)}
              title="Toggle your role in this session"
            >
              Switch to {isHelpee ? 'Helper' : 'Helpee'}
            </button>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Room Code: <strong style={{ color: 'var(--accent-secondary)' }}>{activeSession.session_code}</strong>
            </span>
            <button className="btn btn-secondary btn-sm" onClick={() => setView('trusted-devices')}>
              Trusted Devices
            </button>
            <button className="btn btn-secondary btn-sm" onClick={handleLeaveSession}>
              Dashboard
            </button>
          </div>
        )}
        {(view === 'dashboard' || view === 'trusted-devices') && (
          <button className="btn btn-secondary btn-sm" onClick={() => setView('dashboard')}>
            Dashboard
          </button>
        )}
      </header>

      {/* Main Content Router */}
      <main>
        {view === 'login' && (
          <LoginView
            apiClient={apiClient}
            authStore={authStore}
            onLoginSuccess={() => setView('dashboard')}
            onNavigateToRegister={() => setView('register')}
          />
        )}

        {view === 'register' && (
          <RegisterView
            apiClient={apiClient}
            authStore={authStore}
            onRegisterSuccess={() => setView('dashboard')}
            onNavigateToLogin={() => setView('login')}
          />
        )}

        {view === 'dashboard' && (
          <SessionDashboard
            apiClient={apiClient}
            onEnterSession={handleEnterSession}
            onLogout={handleLogout}
          />
        )}

        {view === 'trusted-devices' && (
          <TrustedDevicesView
            apiClient={apiClient}
            onBack={() => (activeSession ? setView('workspace') : setView('dashboard'))}
          />
        )}

        {view === 'workspace' && activeSession && (
          <div style={{ display: 'flex', minHeight: 'calc(100vh - 72px)' }}>
            {/* Center Canvas & Control Workspace */}
            <div style={{ flex: 1, padding: '1.5rem', display: 'flex', flexDirection: 'column' }}>
              <RemoteCanvasViewport
                sessionId={activeSession.id}
                apiClient={apiClient}
                canvasRenderer={canvasRenderer}
                isFlagSecureActive={isFlagSecure}
              />

              <VoiceControlBar
                sessionId={activeSession.id}
                apiClient={apiClient}
                onSecurityClick={() => setIsSecurityModalOpen(true)}
                onLeaveSession={handleLeaveSession}
              />

              <MultiPartySpeakerGrid
                sessionId={activeSession.id}
                apiClient={apiClient}
                participants={participants}
                isCreator={true}
                onRefreshParticipants={async () => {
                  try {
                    const data = await apiClient.get<ParticipantItem[]>(
                      `/sessions/${activeSession.id}/participants`
                    );
                    setParticipants(data);
                  } catch {
                    // Ignored
                  }
                }}
              />
            </div>

            {/* Right-Side Chat & Chunked File Drawer */}
            <ChatFileDrawer
              sessionId={activeSession.id}
              apiClient={apiClient}
              messages={messages}
              onSendMessage={handleSendMessage}
            />

            {/* E2EE Security & Key Zeroize Modal */}
            <SecurityZeroizeModal
              isOpen={isSecurityModalOpen}
              onClose={() => setIsSecurityModalOpen(false)}
              sessionId={activeSession.id}
              apiClient={apiClient}
              onZeroized={() => {
                addToast('warning', 'Memory Scrubbed', 'E2EE Keys Zeroized');
                setIsSecurityModalOpen(false);
              }}
            />

            {/* One-click help / escalation / drawing overlay flow */}
            <AssistanceCoordinator
              sessionId={activeSession.id}
              apiClient={apiClient}
              sessionManager={sessionManager}
              isHelpee={isHelpee}
              helperDeviceFingerprint={deviceFingerprint}
            />
          </div>
        )}
      </main>

      {/* Toast Notifications */}
      <ToastContainer toasts={toasts} onDismiss={(id) => setToasts((prev) => prev.filter((t) => t.id !== id))} />
    </div>
  );
};

export default App;
