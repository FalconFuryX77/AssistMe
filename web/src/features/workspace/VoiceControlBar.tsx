import React, { useState } from 'react';
import { WebApiClient } from '../../core/network/web_api_client';

export interface VoiceControlBarProps {
  sessionId: string;
  apiClient: WebApiClient;
  onSecurityClick: () => void;
  onLeaveSession: () => void;
}

export const VoiceControlBar: React.FC<VoiceControlBarProps> = ({
  sessionId,
  apiClient,
  onSecurityClick,
  onLeaveSession,
}) => {
  const [isMuted, setIsMuted] = useState(false);
  const [audioRoute, setAudioRoute] = useState<'speaker' | 'earpiece' | 'bluetooth' | 'headset'>('speaker');
  const [degraded, setDegraded] = useState(false);

  const toggleMute = async () => {
    const nextMuted = !isMuted;
    setIsMuted(nextMuted);
    try {
      await apiClient.post(`/sessions/${sessionId}/audio/mute`, {
        is_muted: nextMuted,
      });
    } catch (err) {
      console.warn('Audio mute notice:', err);
    }
  };

  const handleRouteChange = async (route: 'speaker' | 'earpiece' | 'bluetooth' | 'headset') => {
    setAudioRoute(route);
    try {
      await apiClient.post(`/sessions/${sessionId}/audio/route`, {
        audio_route: route,
      });
    } catch (err) {
      console.warn('Audio route notice:', err);
    }
  };

  const triggerAdaptiveMetrics = async () => {
    setDegraded(true);
    try {
      await apiClient.post(`/sessions/${sessionId}/streaming/metrics`, {
        rtt_ms: 120.0,
        jitter_ms: 15.0,
        packet_loss_percent: 2.5,
        available_bandwidth_kbps: 1800,
      });
    } catch (err) {
      console.warn('Metrics report notice:', err);
    }
  };

  return (
    <div className="media-control-bar">
      {/* Mute Toggle */}
      <button
        className={`control-btn ${isMuted ? 'active-muted' : ''}`}
        onClick={toggleMute}
        title={isMuted ? 'Unmute Microphone' : 'Mute Microphone'}
      >
        {isMuted ? '🔇' : '🎙️'}
      </button>

      {/* Audio Output Route Dropdown */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <select
          className="form-input"
          style={{ padding: '0.4rem 0.75rem', fontSize: '0.85rem' }}
          value={audioRoute}
          onChange={(e) => handleRouteChange(e.target.value as any)}
        >
          <option value="speaker">🔊 Speaker</option>
          <option value="earpiece">📱 Earpiece</option>
          <option value="bluetooth">🎧 Bluetooth</option>
          <option value="headset">📻 Headset</option>
        </select>
      </div>

      {/* Adaptive Network Quality Indicator */}
      <button
        className="control-btn"
        onClick={triggerAdaptiveMetrics}
        title="Adaptive Network Quality"
        style={{
          borderColor: degraded ? 'var(--accent-amber)' : 'var(--border-glass)',
        }}
      >
        📶
      </button>

      {/* E2EE / Security Settings */}
      <button
        className="control-btn"
        onClick={onSecurityClick}
        title="E2EE Security & Safety Number"
      >
        🛡️
      </button>

      {/* Disconnect / Leave Session */}
      <button
        className="control-btn active-muted"
        onClick={onLeaveSession}
        title="Leave Assistance Session"
      >
        📞
      </button>
    </div>
  );
};
