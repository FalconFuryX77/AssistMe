import 'dart:convert';
import 'package:flutter/material.dart';
import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/security/secure_storage_service.dart';
import '../../theme/app_theme.dart';
import 'register_screen.dart';
import '../session/session_screen.dart';

class LoginScreen extends StatefulWidget {
  final ApiClient apiClient;
  final SecureStorageService secureStorage;

  const LoginScreen({
    Key? key,
    required this.apiClient,
    required this.secureStorage,
  }) : super(key: key);

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isLoading = false;
  String? _errorMessage;

  Future<void> _handleLogin() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await widget.apiClient.post(
        '/auth/login',
        body: {
          'email': _emailController.text.trim(),
          'password': _passwordController.text,
        },
        requireAuth: false,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        await widget.secureStorage.saveTokens(
          accessToken: data['access_token'],
          refreshToken: data['refresh_token'],
        );

        if (!mounted) return;
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => SessionScreen(
              apiClient: widget.apiClient,
              secureStorage: widget.secureStorage,
            ),
          ),
        );
      } else {
        setState(() {
          _errorMessage = 'Invalid email or password';
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
      body: SafeArea(
        child: Stack(
          children: [
            Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(
                  horizontal: 24.0,
                  vertical: 32.0,
                ),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Logo / Header
                      Center(
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 14,
                            vertical: 6,
                          ),
                          decoration: BoxDecoration(
                            gradient: const LinearGradient(
                              colors: [
                                AppTheme.accentPrimary,
                                AppTheme.accentSecondary,
                              ],
                            ),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: const Text(
                            'ACSAF',
                            style: TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.w800,
                              fontSize: 12,
                              letterSpacing: 1.2,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'AssistMe',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Adaptive Context-Aware Remote Assistance',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 13,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                      const SizedBox(height: 36),

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
                            style: const TextStyle(
                              color: AppTheme.accentRose,
                              fontSize: 13,
                            ),
                          ),
                        ),

                      // Email Input
                      TextFormField(
                        controller: _emailController,
                        keyboardType: TextInputType.emailAddress,
                        style: const TextStyle(color: AppTheme.textPrimary),
                        decoration: const InputDecoration(
                          labelText: 'Email Address',
                          hintText: 'user@example.com',
                          prefixIcon: Icon(
                            Icons.email_outlined,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                        validator: (val) {
                          if (val == null || !val.contains('@'))
                            return 'Enter a valid email';
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),

                      // Password Input
                      TextFormField(
                        controller: _passwordController,
                        obscureText: true,
                        style: const TextStyle(color: AppTheme.textPrimary),
                        decoration: const InputDecoration(
                          labelText: 'Password',
                          hintText: '••••••••',
                          prefixIcon: Icon(
                            Icons.lock_outline,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                        validator: (val) {
                          if (val == null || val.length < 8)
                            return 'Password must be at least 8 characters';
                          return null;
                        },
                      ),
                      const SizedBox(height: 24),

                      // Submit Button
                      ElevatedButton(
                        onPressed: _isLoading ? null : _handleLogin,
                        child: _isLoading
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  color: Colors.white,
                                  strokeWidth: 2,
                                ),
                              )
                            : const Text('Sign In'),
                      ),
                      const SizedBox(height: 20),

                      // Navigate to Register
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Text(
                            "Don't have an account? ",
                            style: TextStyle(
                              color: AppTheme.textSecondary,
                              fontSize: 13,
                            ),
                          ),
                          GestureDetector(
                            onTap: () {
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) => RegisterScreen(
                                    apiClient: widget.apiClient,
                                    secureStorage: widget.secureStorage,
                                  ),
                                ),
                              );
                            },
                            child: const Text(
                              'Register',
                              style: TextStyle(
                                color: AppTheme.accentPrimary,
                                fontWeight: FontWeight.w700,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
            // Server settings gear (top-right)
            Positioned(
              top: 8,
              right: 8,
              child: IconButton(
                tooltip: 'Server Settings',
                icon: const Icon(Icons.settings_outlined),
                onPressed: _showServerSettings,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Let the user change the backend server address at runtime.
  /// This makes it possible to point the app at a public internet URL
  /// (e.g. https://your-host.com) without rebuilding the app.
  Future<void> _showServerSettings() async {
    final controller = TextEditingController(text: AppConfig.baseUrl);
    final saved = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Server Address'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Address of the AssistMe backend. Use http://<LAN-IP>:8000 '
              'on your home Wi-Fi, or a public https:// URL to connect over '
              'the internet.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              keyboardType: TextInputType.url,
              style: const TextStyle(color: AppTheme.textPrimary),
              decoration: const InputDecoration(
                labelText: 'Backend URL',
                hintText: 'http://192.168.1.50:8000 or https://example.com',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              var url = controller.text.trim();
              if (!url.startsWith('http://') && !url.startsWith('https://')) {
                url = 'http://$url';
              }
              Navigator.pop(ctx, url);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (saved == null || saved.isEmpty || !mounted) return;
    setState(() {
      AppConfig.baseUrl = saved;
      widget.apiClient.baseUrl = saved;
    });
    await widget.secureStorage.saveServerUrl(saved);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Server set to $saved — reconnect to use it')),
    );
  }
}
