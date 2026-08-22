import 'dart:convert';
import 'package:flutter/material.dart';
import '../../core/network/api_client.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';
import '../devices/trusted_devices_screen.dart';
import '../workspace/mobile_workspace_screen.dart';
import 'bloc/session_bloc.dart';

class SessionScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const SessionScreen({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
  }) : super(key: key);

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  final _sessionBloc = SessionBloc();
  final _codeController = TextEditingController();
  final _titleController = TextEditingController(text: 'Mobile Assistance Session');
  int _timeoutMinutes = 30;
  bool _isLoading = false;
  String? _errorMessage;

  Future<void> _handleJoinSession() async {
    final code = _codeController.text.trim().toUpperCase();
    if (code.isEmpty) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await _sessionBloc.handleEvent(JoinSessionEvent(sessionCode: code));
      final response = await widget.apiClient.post(
        '/sessions/join',
        body: {'session_code': code},
      );

      if (response.statusCode == 200) {
        final session = jsonDecode(response.body);
        if (!mounted) return;
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => MobileWorkspaceScreen(
              sessionId: session['id'],
              sessionCode: session['session_code'],
              apiClient: widget.apiClient,
              secureStorage: widget.secureStorage,
            ),
          ),
        );
      } else {
        setState(() {
          _errorMessage = 'Invalid or expired session code';
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Failed to join session: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _handleCreateSession() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await _sessionBloc.handleEvent(CreateSessionEvent(title: _titleController.text));
      final response = await widget.apiClient.post(
        '/sessions/',
        body: {
          'title': _titleController.text.trim(),
          'timeout_minutes': _timeoutMinutes,
        },
      );

      if (response.statusCode == 201) {
        final session = jsonDecode(response.body);
        if (!mounted) return;
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => MobileWorkspaceScreen(
              sessionId: session['id'],
              sessionCode: session['session_code'],
              apiClient: widget.apiClient,
              secureStorage: widget.secureStorage,
            ),
          ),
        );
      } else {
        setState(() {
          _errorMessage = 'Failed to create session';
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Network connection failed: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Assistance Sessions'),
        actions: [
          IconButton(
            tooltip: 'Trusted Devices',
            icon: const Icon(Icons.verified_user_outlined),
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => TrustedDevicesScreen(
                    apiClient: widget.apiClient,
                    secureStorage: widget.secureStorage,
                  ),
                ),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await widget.secureStorage.clearAll();
              if (!mounted) return;
              Navigator.of(context).pop();
            },
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_errorMessage != null)
                Container(
                  padding: const EdgeInsets.all(12),
                  margin: const EdgeInsets.only(bottom: 20),
                  decoration: BoxDecoration(
                    color: AppTheme.accentRose.withOpacity(0.15),
                    border: Border.all(color: AppTheme.accentRose),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _errorMessage!,
                    style: const TextStyle(color: AppTheme.accentRose, fontSize: 13),
                  ),
                ),

              // Quick Join Card
              Card(
                color: AppTheme.bgSecondary,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                  side: const BorderSide(color: AppTheme.borderGlass),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(20.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        'Join Live Session',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Enter 6-character alphanumeric code',
                        style: TextStyle(fontSize: 13, color: AppTheme.textSecondary),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _codeController,
                        textCapitalization: TextCapitalization.characters,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 6,
                          color: AppTheme.accentSecondary,
                        ),
                        decoration: const InputDecoration(
                          hintText: 'ABC123',
                          contentPadding: EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                      const SizedBox(height: 16),
                      ElevatedButton(
                        onPressed: _isLoading ? null : _handleJoinSession,
                        child: const Text('Connect to Room'),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 24),

              // Create Session Card
              Card(
                color: AppTheme.bgSecondary,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                  side: const BorderSide(color: AppTheme.borderGlass),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(20.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        'Create New Assistance Room',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _titleController,
                        style: const TextStyle(color: AppTheme.textPrimary),
                        decoration: const InputDecoration(
                          labelText: 'Session Title',
                          hintText: 'Help with device settings',
                        ),
                      ),
                      const SizedBox(height: 16),
                      DropdownButtonFormField<int>(
                        value: _timeoutMinutes,
                        dropdownColor: AppTheme.bgSecondary,
                        decoration: const InputDecoration(labelText: 'Timeout'),
                        items: const [
                          DropdownMenuItem(value: 15, child: Text('15 Minutes')),
                          DropdownMenuItem(value: 30, child: Text('30 Minutes')),
                          DropdownMenuItem(value: 60, child: Text('60 Minutes')),
                        ],
                        onChanged: (val) {
                          if (val != null) setState(() => _timeoutMinutes = val);
                        },
                      ),
                      const SizedBox(height: 20),
                      ElevatedButton(
                        onPressed: _isLoading ? null : _handleCreateSession,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.accentEmerald,
                        ),
                        child: const Text('Start New Session'),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
