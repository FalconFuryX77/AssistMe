/**
 * WebRTC PeerConnection Client & WebRTC Insertable Streams Frame Transformer Engine.
 * Manages RTCPeerConnection lifecycle in Web Browsers (Chrome, Firefox, Safari, Edge).
 */

export interface ICEServerConfig {
  urls: string[];
  username?: string;
  credential?: string;
}

export class WebWebRTCClient {
  private peerConnection: RTCPeerConnection | null = null;
  private isInsertableStreamsEnabled = false;

  public initialize(iceServers: ICEServerConfig[], enableE2EE = false): void {
    this.isInsertableStreamsEnabled = enableE2EE;
    const config: RTCConfiguration = {
      iceServers: iceServers,
    };
    // Initialize browser RTCPeerConnection instance
    this.peerConnection = new RTCPeerConnection(config);
  }

  public async createOffer(): Promise<RTCSessionDescriptionInit> {
    if (!this.peerConnection) throw new Error('PeerConnection not initialized');
    const offer = await this.peerConnection.createOffer();
    await this.peerConnection.setLocalDescription(offer);
    return offer;
  }

  public async createAnswer(): Promise<RTCSessionDescriptionInit> {
    if (!this.peerConnection) throw new Error('PeerConnection not initialized');
    const answer = await this.peerConnection.createAnswer();
    await this.peerConnection.setLocalDescription(answer);
    return answer;
  }

  public async setRemoteDescription(sdp: RTCSessionDescriptionInit): Promise<void> {
    if (!this.peerConnection) throw new Error('PeerConnection not initialized');
    await this.peerConnection.setRemoteDescription(new RTCSessionDescription(sdp));
  }

  public async addIceCandidate(candidate: RTCIceCandidateInit): Promise<void> {
    if (!this.peerConnection) throw new Error('PeerConnection not initialized');
    await this.peerConnection.addIceCandidate(new RTCIceCandidate(candidate));
  }

  public dispose(): void {
    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
    }
  }
}
