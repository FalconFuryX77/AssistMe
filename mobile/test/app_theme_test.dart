import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:assistme/theme/app_theme.dart';

void main() {
  tearDown(() => AppTheme.setDarkMode(true));

  test('light mode uses dark text on light surfaces', () {
    AppTheme.setDarkMode(false);

    expect(AppTheme.bgPrimary, const Color(0xFFF1F5F9));
    expect(AppTheme.bgSecondary, Colors.white);
    expect(AppTheme.textPrimary, const Color(0xFF0F172A));
    expect(AppTheme.textSecondary, const Color(0xFF334155));
    expect(AppTheme.textMuted, const Color(0xFF475569));
    expect(AppTheme.borderGlass, const Color(0x1E000000));
  });

  test('dark mode restores the dark palette', () {
    AppTheme.setDarkMode(true);

    expect(AppTheme.bgPrimary, const Color(0xFF0A0F1D));
    expect(AppTheme.bgSecondary, const Color(0xFF131B2E));
    expect(AppTheme.textPrimary, const Color(0xFFF9FAFB));
    expect(AppTheme.textSecondary, const Color(0xFFCBD5E1));
    expect(AppTheme.textMuted, const Color(0xFF94A3B8));
  });
}
