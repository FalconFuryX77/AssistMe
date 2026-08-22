import React, { useState, useEffect } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';
import { getBrowserFingerprint } from '../../core/security/browser_device_identity';
import { Button } from '../../components/common/Button';

interface TrustedDevice {
  id: string;
  owner_user_id: string;
  device_fingerprint: string;
  friendly_name: string | null;
  device_platform: string | null;
  status: string;
  last_seen_at: string | null;
  created_at: string;
}

interface TrustedDeviceListResponse {
  total: number;
  devices: TrustedDevice[];
}

export interface TrustedDevicesViewProps {
  apiClient: WebApiClient;
  onBack: () => void;
}

export const TrustedDevicesView: React.FC<TrustedDevicesViewProps> = ({ apiClient, onBack }) => {
  const [devices, setDevices] = useState<TrustedDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showPair, setShowPair] = useState(false);
  const [fingerprint, setFingerprint] = useState('');
  const [friendlyName, setFriendlyName] = useState('');
  const [pairingCode, setPairingCode] = useState('');
  const [confirmCode, setConfirmCode] = useState('');
  const [password, setPassword] = useState('');

  const ownFingerprint = getBrowserFingerprint();

  const fetchDevices = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.listTrustedDevices() as unknown as TrustedDeviceListResponse;
      setDevices(data.devices);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load devices');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDevices();
  }, []);

  const copyOwnFingerprint = async () => {
    try {
      await navigator.clipboard.writeText(ownFingerprint);
      setError(null);
      window.alert('Your Device ID copied to clipboard — paste it into the person you want to help you.');
    } catch {
      setError('Could not copy — select the ID below and copy manually.');
    }
  };

  const handleInitiatePairing = async () => {
    setError(null);
    if (!fingerprint.trim()) {
      setError('Paste the Device ID from the device that will help you.');
      return;
    }
    try {
      const data = await apiClient.initiatePairing(fingerprint.trim(), friendlyName.trim() || 'Helper Device', 'browser') as unknown as {
        pairing_code: string;
        expires_at: string;
      };
      setPairingCode(data.pairing_code);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to initiate pairing');
    }
  };

  const handleConfirmPairing = async () => {
    setError(null);
    if (!confirmCode.trim() || !password) {
      setError('Enter the code and your password');
      return;
    }
    try {
      await apiClient.confirmPairing(confirmCode.trim(), password);
      setShowPair(false);
      setPairingCode('');
      setConfirmCode('');
      setPassword('');
      setFingerprint('');
      setFriendlyName('');
      await fetchDevices();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pairing failed');
    }
  };

  const handleRevoke = async (deviceId: string) => {
    setError(null);
    const pw = window.prompt('Enter your password to revoke this device (trusted list is password protected):');
    if (!pw) return;
    try {
      await apiClient.revokeDevice(deviceId, pw);
      await fetchDevices();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Revoke failed');
    }
  };

  return (
    <div style={{ maxWidth: '1000px', margin: '0 auto', padding: '2rem 1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', marginBottom: '0.25rem' }}>Trusted Devices</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Only these devices can connect to guide you. The list is password protected.
          </p>
        </div>
        <Button variant="secondary" onClick={onBack}>
          Back
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

      <div className="glass-panel" style={{ padding: '1.75rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15rem', marginBottom: '1rem' }}>How to connect two devices</h2>
        <ol style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.7, margin: 0, paddingLeft: '1.25rem' }}>
          <li><strong style={{ color: 'var(--text-primary)' }}>On this page you are the OWNER (the person being helped).</strong></li>
          <li>On the device that will <strong>help you</strong>, open its Trusted Devices screen and copy its <strong>Device ID</strong> (shown at the top of that screen).</li>
          <li>Come back here, press <strong>+ Pair New Device</strong>, paste that Device ID, and name it.</li>
          <li>Press <strong>Generate Pairing Code</strong>, then enter the code shown plus <strong>your password</strong> and press <strong>Authorize Device</strong>.</li>
          <li>That device now appears in <strong>Your Trusted Devices</strong> below and may assist you.</li>
        </ol>
      </div>

      <div className="glass-panel" style={{ padding: '1.75rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15rem', marginBottom: '0.75rem' }}>This device&apos;s ID</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
          If someone else needs to trust THIS device (because you will help them),
          send them this ID so they can paste it into their Trusted Devices screen.
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <code style={{ fontFamily: 'monospace', background: 'var(--bg-primary)', border: '1px solid var(--border-glass)', borderRadius: 'var(--radius-sm)', padding: '0.5rem 0.75rem', color: 'var(--accent-secondary)', wordBreak: 'break-all' }}>
            {ownFingerprint}
          </code>
          <Button variant="secondary" size="sm" onClick={copyOwnFingerprint}>
            Copy
          </Button>
        </div>
      </div>

      <div className="glass-panel" style={{ padding: '1.75rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15rem', marginBottom: '1rem' }}>Pair a New Device</h2>
        {!showPair ? (
          <Button variant="primary" onClick={() => setShowPair(true)}>
            + Pair New Device
          </Button>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="form-group">
              <label className="form-label">Helper&apos;s Device ID (paste the ID shown on the helper&apos;s screen)</label>
              <input
                className="form-input"
                placeholder="assistme-4f2a... or browser-4f2a..."
                value={fingerprint}
                onChange={(e) => setFingerprint(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Name for this device (optional)</label>
              <input
                className="form-input"
                placeholder="Helper Phone"
                value={friendlyName}
                onChange={(e) => setFriendlyName(e.target.value)}
              />
            </div>
            {!pairingCode ? (
              <div>
                <Button variant="primary" onClick={handleInitiatePairing}>
                  Generate Pairing Code
                </Button>
              </div>
            ) : (
              <>
                <div
                  style={{
                    padding: '1rem',
                    background: 'var(--bg-primary)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: 'var(--radius-md)',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    Enter this code below, then confirm with your own password:
                  </div>
                  <strong style={{ fontSize: '1.75rem', letterSpacing: '0.4em', color: 'var(--accent-secondary)' }}>
                    {pairingCode}
                  </strong>
                </div>
                <div className="form-group">
                  <label className="form-label">Confirm code (enter the code shown above)</label>
                  <input
                    className="form-input"
                    placeholder="000000"
                    value={confirmCode}
                    onChange={(e) => setConfirmCode(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Your password (confirms you are the owner)</label>
                  <input
                    className="form-input"
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <Button variant="primary" onClick={handleConfirmPairing}>
                    Authorize Device
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setShowPair(false);
                      setPairingCode('');
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="glass-panel" style={{ padding: '1.75rem' }}>
        <h2 style={{ fontSize: '1.15rem', marginBottom: '1rem' }}>
          Your Trusted Devices ({devices.length})
        </h2>
        {loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading...</p>
        ) : devices.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            No trusted devices yet. Pair one above.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {devices.map((d) => (
              <div
                key={d.id}
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
                  <div style={{ fontWeight: 600 }}>{d.friendly_name ?? d.device_fingerprint.slice(0, 24)}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                    {d.device_platform ?? 'unknown'} &bull; {d.status} &bull; {new Date(d.created_at).toLocaleString()}
                  </div>
                </div>
                <Button variant="danger" size="sm" onClick={() => handleRevoke(d.id)}>
                  Revoke
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};