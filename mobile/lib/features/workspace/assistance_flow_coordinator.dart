/// Assistance flow coordinator — wires the realtime channel to the security UI.
///
/// Handles the full one-click help experience:
///   - helpee taps "request help" → popup on helper
///   - helper accepts (overlay-only) / denies
///   - helper requests escalation → helpee sees risk disclaimer
///   - helpee accepts risks → control granted
///   - helper draw strokes are rendered on the overlay
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../../core/network/api_client.dart';
import '../../core/realtime/realtime_service.dart';
import '../../core/security/device_identity.dart';
import '../../core/security/secure_storage_service.dart';
import '../../core/webrtc/webrtc_engine.dart';
import '../../theme/app_theme.dart';
import 'drawing_overlay.dart';
import 'incoming_help_request_popup.dart';
import 'risk_disclaimer_modal.dart';

class AssistanceFlowCoordinator extends StatefulWidget {
  final String sessionId;
  final ApiClient apiClient;
  final SecureStorageService secureStorage;
  final bool isHelpee;

  /// Sink the coordinator publishes the remote WebRTC stream into so sibling
  /// widgets (e.g. the remote viewport) can render it without rebuilding.
  final ValueNotifier<dynamic>? remoteStreamSink;

  const AssistanceFlowCoordinator({
    Key? key,
    required this.sessionId,
    required this.apiClient,
    required this.secureStorage,
    required this.isHelpee,
    this.remoteStreamSink,
  }) : super(key: key);

  @override
  State<AssistanceFlowCoordinator> createState() => AssistanceFlowCoordinatorState();
}

class AssistanceFlowCoordinatorState extends State<AssistanceFlowCoordinator> {
  RealtimeService? _realtime;
  List<DrawStroke> _strokes = [];
  String? _helperDeviceFingerprint;
  bool _isRequestingHelp = false;

  // Pending incoming request / escalation
  String? _pendingRequestId;
  Map<String, dynamic>? _pendingEscalation;

  // WebRTC media pipeline (screen share + two-way voice)
  final WebRTCEngine _engine = WebRTCEngine();
  late final ValueNotifier<dynamic> remoteStreamNotifier =
      widget.remoteStreamSink ?? ValueNotifier<dynamic>(null);
  bool _mediaReady = false;
  bool _screenShareStarted = false;

  bool get isMediaReady => _mediaReady;
  bool get isScreenShareStarted => _screenShareStarted;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    final fingerprint = await DeviceIdentity.getFingerprint(widget.secureStorage);
    final token = await widget.secureStorage.getAccessToken();
    setState(() => _helperDeviceFingerprint = fingerprint);

    if (token != null) {
      try {
        _realtime = RealtimeService(sessionId: widget.sessionId, accessToken: token);
        await _realtime!.connect();
        _realtime!.events.listen(_onEvent);
      } catch (e) {
        debugPrint('Realtime connect failed: $e');
      }
    }

    await _initMediaEngine();
  }

  // ------------------------------------------------------------------
  // WebRTC media pipeline (screen share + two-way voice)
  // ------------------------------------------------------------------

  Future<void> _initMediaEngine() async {
    List<Map<String, dynamic>> iceServers = const [
      {'urls': 'stun:stun.l.google.com:19302'},
    ];
    try {
      final resp = await widget.apiClient.getIceServers(widget.sessionId);
      if (resp.statusCode == 200) {
        final servers = jsonDecode(resp.body)['ice_servers'] as List;
        iceServers = servers.map<Map<String, dynamic>>((s) {
          final m = Map<String, dynamic>.from(s as Map);
          // Android's IceServer builder throws on explicit null
          // username/credential keys sent for plain STUN entries.
          m.removeWhere((k, v) => v == null);
          return m;
        }).toList();
      }
    } catch (_) {
      // fall back to default STUN-only config
    }

    try {
      _engine.onLocalCandidate = (candidate) {
        _realtime?.send({'type': 'signal_ice_candidate', 'candidate': candidate});
      };
      _engine.onRemoteStream = (stream) {
        // The helpee publishes screen video and mic audio as separate
        // streams; keep whichever carries video for the viewport (remote
        // audio plays through the peer connection regardless).
        final current = remoteStreamNotifier.value;
        if (current == null || stream.getVideoTracks().isNotEmpty) {
          remoteStreamNotifier.value = stream;
        }
      };
      await _engine.initialize(iceServers: iceServers);
      if (mounted) setState(() => _mediaReady = true);
    } catch (e) {
      debugPrint('WebRTC init failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          backgroundColor: AppTheme.accentRose,
          content: Text('Media engine failed to start: $e'),
        ));
      }
    }
  }

  /// Helpee: capture screen + mic, then offer to the room.
  Future<void> startScreenShare() async {
    if (_screenShareStarted || !_mediaReady) return;
    try {
      await _engine.startScreenCapture();
      final offer = await _engine.createOffer();
      _realtime?.send({'type': 'signal_offer', 'sdp': offer});
      _realtime?.send({'type': 'screen_share_start', 'platform': 'android'});
      if (mounted) setState(() => _screenShareStarted = true);
    } catch (e) {
      debugPrint('Screen share failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not start sharing: $e')),
        );
      }
    }
  }

  Future<void> stopScreenShare() async {
    if (!_screenShareStarted) return;
    try {
      await _engine.stopScreenCapture();
      _realtime?.send({'type': 'screen_share_stop'});
      if (mounted) setState(() => _screenShareStarted = false);
    } catch (e) {
      debugPrint('Stop screen share failed: $e');
    }
  }

  /// Helper: answer an incoming screen-share offer with our mic attached.
  Future<void> _handleIncomingOffer(Map<String, dynamic> sdp) async {
    if (!_mediaReady || remoteStreamNotifier.value != null) return;
    try {
      await _engine.setRemoteDescription(sdp);
      await _engine.startMicOnly();
      final answer = await _engine.createAnswer();
      _realtime?.send({'type': 'signal_answer', 'sdp': answer});
    } catch (e) {
      debugPrint('Answering offer failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          backgroundColor: AppTheme.accentRose,
          content: Text('Could not join the call: $e'),
        ));
      }
    }
  }

  void _onEvent(RealtimeEvent event) {
    switch (event.type) {
      case 'assistance_requested':
        // A helpee is asking us (helper) for help.
        final requestId = event.data['request_id'];
        if (widget.isHelpee) break;
        setState(() {
          _pendingRequestId = requestId;
        });
        break;

      case 'escalation_requested':
        // Helper wants more control; we are the helpee.
        final escalationId = event.data['escalation_id'];
        final disclaimer = event.data['disclaimer_text'];
        if (!widget.isHelpee) break;
        setState(() {
          _pendingEscalation = {
            'id': escalationId,
            'disclaimer_text': disclaimer ?? '',
          };
        });
        break;

      case 'draw_stroke':
        // Helper sends draw points for the overlay.
        final raw = event.data['points'];
        if (raw is List) {
          final points = <Offset>[];
          for (final item in raw) {
            if (item is Map) {
              final dx = item['x'] as num;
              final dy = item['y'] as num;
              points.add(Offset(dx.toDouble(), dy.toDouble()));
            }
          }
          setState(() => _strokes.add(DrawStroke(points: points)));
        }
        break;

      case 'draw_clear':
        setState(() => _strokes.clear());
        break;

      // --- WebRTC signaling relay ---
      case 'signal_offer':
        if (!widget.isHelpee) {
          final sdp = event.data['sdp'];
          if (sdp is Map) _handleIncomingOffer(Map<String, dynamic>.from(sdp));
        }
        break;

      case 'signal_answer':
        if (widget.isHelpee) {
          final sdp = event.data['sdp'];
          if (sdp is Map) {
            _engine
                .setRemoteDescription(Map<String, dynamic>.from(sdp))
                .catchError((e) {
              debugPrint('Applying answer failed: $e');
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  backgroundColor: AppTheme.accentRose,
                  content: Text('Connection problem: $e'),
                ));
              }
            });
          }
        }
        break;

      case 'signal_ice_candidate':
        final candidate = event.data['candidate'];
        if (candidate is Map) {
          _engine.addIceCandidate(Map<String, dynamic>.from(candidate));
        }
        break;

      case 'assistance_request_responded':
        // Helper accepted: helpee starts sharing automatically.
        if (widget.isHelpee &&
            event.data['status'] == 'accepted' &&
            !_screenShareStarted) {
          startScreenShare();
        }
        break;

      case 'screen_share_stop':
        if (!widget.isHelpee) remoteStreamNotifier.value = null;
        break;
      case 'session_ended':
        stopScreenShare();
        break;
    }
  }

  // ------------------------------------------------------------------
  // Helpee actions
  // ------------------------------------------------------------------

  bool get isRequestingHelp => _isRequestingHelp;

  Future<void> requestHelp() async {
    if (_isRequestingHelp) return;

    // Load the trusted devices so the user can pick the helper's device.
    List<Map<String, dynamic>> trusted = [];
    try {
      final resp = await widget.apiClient.listTrustedDevices();
      if (resp.statusCode == 200) {
        trusted = List<Map<String, dynamic>>.from(jsonDecode(resp.body)['devices']);
      }
    } catch (_) {
      // fall through, dialog will explain
    }

    final selection = await _promptHelperSelection(trusted);
    if (selection == null) return;
    final helperUserId = selection['userId'] as String;
    final helperFingerprint = selection['fingerprint'] as String;

    setState(() => _isRequestingHelp = true);
    try {
      final resp = await widget.apiClient.requestHelp(
        sessionId: widget.sessionId,
        helperUserId: helperUserId,
        helperDeviceFingerprint: helperFingerprint,
      );
      if (resp.statusCode == 201) {
        // Broadcast the request to the room (helper will see the popup).
        _realtime?.send({
          'type': 'assistance_requested',
          'request_id': jsonDecode(resp.body)['id'],
          'helper_user_id': helperUserId,
          'helpee_user_id': helperUserId,
        });
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Request failed';
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    } finally {
      if (mounted) setState(() => _isRequestingHelp = false);
    }
  }

  /// Ask who to request help from. Requires the helper's user ID AND the
  /// helper's device fingerprint (must match a trusted device).
  Future<Map<String, String>?> _promptHelperSelection(List<Map<String, dynamic>> trusted) async {
    final userIdController = TextEditingController();
    final fingerprintController = TextEditingController();

    // Pre-fill the fingerprint with the first trusted device if present.
    if (trusted.isNotEmpty) {
      fingerprintController.text = trusted.first['device_fingerprint'] as String? ?? '';
    }

    return showDialog<Map<String, String>>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Request Help'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'This phone is the HELPEE (person being helped). Pick the '
                'helper and their trusted device.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              ),
              const SizedBox(height: 12),
              if (trusted.isEmpty)
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppTheme.accentRose.withOpacity(0.12),
                    border: Border.all(color: AppTheme.accentRose),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Text(
                    'No trusted devices yet. Go to Trusted Devices and pair '
                    'the helper\'s device first (paste their Device ID).',
                    style: TextStyle(color: AppTheme.accentRose, fontSize: 12),
                  ),
                )
              else
                Text(
                  'Trusted helper devices: ${trusted.map((d) => (d['friendly_name'] ?? 'device')).join(', ')}',
                  style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
                ),
              const SizedBox(height: 12),
              TextField(
                controller: userIdController,
                style: const TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: "Helper's user ID",
                  hintText: 'Paste the helper user id',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: fingerprintController,
                style: const TextStyle(color: AppTheme.textPrimary),
                decoration: const InputDecoration(
                  labelText: "Helper's Device ID",
                  hintText: 'assistme-... or browser-...',
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'The Device ID must match one you already paired in Trusted '
                'Devices, or the request will be rejected.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 12),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              final userId = userIdController.text.trim();
              final fp = fingerprintController.text.trim();
              if (userId.isEmpty || fp.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Enter both the user ID and Device ID')),
                );
                return;
              }
              Navigator.pop(ctx, {'userId': userId, 'fingerprint': fp});
            },
            child: const Text('Send'),
          ),
        ],
      ),
    );
  }

  Future<void> _respondToEscalation({required bool accept}) async {
    final escalation = _pendingEscalation;
    if (escalation == null) return;

    try {
      final resp = await widget.apiClient.respondToEscalation(
        sessionId: widget.sessionId,
        escalationId: escalation['id'],
        accept: accept,
        acceptDisclaimer: accept,
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (data['status'] == 'approved') {
          _realtime?.send({'type': 'escalation_responded', 'escalation_id': escalation['id'], 'status': 'approved'});
        }
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Escalation failed';
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    }
    if (mounted) setState(() => _pendingEscalation = null);
  }

  // ------------------------------------------------------------------
  // Helper actions
  // ------------------------------------------------------------------

  Future<void> _respondToRequest({required bool accept}) async {
    final requestId = _pendingRequestId;
    if (requestId == null) return;

    try {
      final resp = await widget.apiClient.respondToHelpRequest(
        sessionId: widget.sessionId,
        requestId: requestId,
        accept: accept,
        helperDeviceFingerprint: _helperDeviceFingerprint,
      );
      if (resp.statusCode == 200) {
        _realtime?.send({'type': 'assistance_request_responded', 'request_id': requestId, 'status': 'accepted'});
      }
    } catch (e) {
      debugPrint('Respond request failed: $e');
    }
    if (mounted) setState(() => _pendingRequestId = null);
  }

  Future<void> _requestEscalation() async {
    final capabilities = await _promptCapabilities();
    if (capabilities == null) return;

    try {
      final resp = await widget.apiClient.requestEscalation(
        sessionId: widget.sessionId,
        targetCapabilities: capabilities,
      );
      if (resp.statusCode == 201) {
        final data = jsonDecode(resp.body);
        _realtime?.send({
          'type': 'escalation_requested',
          'escalation_id': data['id'],
          'target_capabilities': capabilities,
          'disclaimer_text': data['disclaimer_text'],
        });
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Control request sent — awaiting helpee approval')),
          );
        }
      } else {
        final detail = jsonDecode(resp.body)['detail'] ?? 'Escalation failed';
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(detail.toString())));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Network error: $e')));
      }
    }
  }

  Future<List<String>?> _promptCapabilities() async {
    final tap = <String, bool>{'tap': false, 'drag': false, 'pointer': false, 'voice': true};
    return showDialog<List<String>>(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setDialogState) => AlertDialog(
            backgroundColor: AppTheme.bgSecondary,
            title: const Text('Request More Control'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CheckboxListTile(
                  title: const Text('Tap / interact'),
                  value: tap['tap'],
                  onChanged: (v) => setDialogState(() => tap['tap'] = v ?? false),
                ),
                CheckboxListTile(
                  title: const Text('Drag / scroll'),
                  value: tap['drag'],
                  onChanged: (v) => setDialogState(() => tap['drag'] = v ?? false),
                ),
                CheckboxListTile(
                  title: const Text('Pointer / annotation'),
                  value: tap['pointer'],
                  onChanged: (v) => setDialogState(() => tap['pointer'] = v ?? false),
                ),
              ],
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
              ElevatedButton(
                onPressed: () {
                  final selected = tap.entries.where((e) => e.value).map((e) => e.key).toList();
                  Navigator.pop(ctx, selected);
                },
                child: const Text('Request'),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // Drawing overlay (renders helper strokes on top of the viewport)
        if (_strokes.isNotEmpty)
          Positioned.fill(child: DrawingOverlay(strokes: _strokes)),

        // Helper: incoming assistance request popup
        if (_pendingRequestId != null)
          Positioned.fill(
            child: Container(
              color: Colors.black54,
              child: Center(
                child: IncomingHelpRequestPopup(
                  helperDeviceFingerprint: _helperDeviceFingerprint ?? '',
                  onAccept: () => _respondToRequest(accept: true),
                  onDeny: () => _respondToRequest(accept: false),
                ),
              ),
            ),
          ),

        // Helpee: escalation risk disclaimer popup
        if (_pendingEscalation != null)
          Positioned.fill(
            child: Container(
              color: Colors.black54,
              child: Center(
                child: RiskDisclaimerModal(
                  disclaimerText: _pendingEscalation!['disclaimer_text'] ?? '',
                  onAccept: () => _respondToEscalation(accept: true),
                  onDecline: () => _respondToEscalation(accept: false),
                ),
              ),
            ),
          ),

        // Helper: floating "request control" button
        if (!widget.isHelpee)
          Positioned(
            top: 16,
            right: 16,
            child: FloatingActionButton.small(
              heroTag: 'request_control',
              backgroundColor: AppTheme.accentSecondary,
              onPressed: _requestEscalation,
              child: const Icon(Icons.open_in_full),
            ),
          ),
      ],
    );
  }
}