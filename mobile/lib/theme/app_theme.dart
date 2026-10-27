import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// AssistMe Design System & Theme Tokens.
/// Specially optimized for high contrast, elderly accessibility, and premium native feel.
class AppTheme {
  // Deep space / slate backgrounds
  static const Color bgPrimary = Color(0xFF0A0F1D);
  static const Color bgSecondary = Color(0xFF131B2E);
  static const Color bgCard = Color(0xFF1A243B);
  static const Color bgCardElevated = Color(0xFF22304E);
  
  // Glassmorphic border tokens
  static const Color borderGlass = Color(0x24FFFFFF);
  static const Color borderGlassStrong = Color(0x40FFFFFF);
  static const Color borderGlow = Color(0x3310B981);

  // Vibrant, high-contrast semantic accents
  static const Color accentPrimary = Color(0xFF6366F1); // Indigo (Helper primary)
  static const Color accentSecondary = Color(0xFF06B6D4); // Cyan (Highlights)
  static const Color accentEmerald = Color(0xFF10B981); // Emerald (Helpee action & call)
  static const Color accentEmeraldGlow = Color(0xFF059669);
  static const Color accentRose = Color(0xFFEF4444); // Rose/Red (Panic stop, decline, error)
  static const Color accentAmber = Color(0xFFF59E0B); // Amber (Pending status, warnings)

  // Typography contrast tokens (WCAG AAA compliant on dark)
  static const Color textPrimary = Color(0xFFF9FAFB);
  static const Color textSecondary = Color(0xFFCBD5E1);
  static const Color textMuted = Color(0xFF94A3B8);

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: bgPrimary,
      primaryColor: accentEmerald,
      colorScheme: const ColorScheme.dark(
        primary: accentEmerald,
        secondary: accentPrimary,
        surface: bgSecondary,
        error: accentRose,
        onPrimary: Colors.white,
        onSurface: textPrimary,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: bgPrimary,
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarIconBrightness: Brightness.light,
          statusBarBrightness: Brightness.dark,
        ),
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: true,
        titleTextStyle: TextStyle(
          color: textPrimary,
          fontSize: 22,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.5,
        ),
        iconTheme: IconThemeData(color: textPrimary, size: 24),
      ),
      cardTheme: CardThemeData(
        color: bgSecondary,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: borderGlass),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: accentEmerald,
          foregroundColor: Colors.white,
          elevation: 2,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          minimumSize: const Size(88, 56), // Minimum 56dp touch target for accessibility
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          textStyle: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.2,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: textPrimary,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          minimumSize: const Size(88, 54),
          side: const BorderSide(color: borderGlassStrong, width: 1.5),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: accentSecondary,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: bgCard,
        hintStyle: const TextStyle(color: textMuted, fontSize: 16),
        labelStyle: const TextStyle(color: textSecondary, fontSize: 16, fontWeight: FontWeight.w500),
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: borderGlass),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: borderGlass),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: accentEmerald, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: accentRose, width: 1.5),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: bgSecondary,
        elevation: 8,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(24),
          side: const BorderSide(color: borderGlassStrong),
        ),
        titleTextStyle: const TextStyle(
          color: textPrimary,
          fontSize: 22,
          fontWeight: FontWeight.w800,
        ),
        contentTextStyle: const TextStyle(
          color: textSecondary,
          fontSize: 16,
          height: 1.4,
        ),
      ),
    );
  }

  static ThemeData get lightTheme {
    const bgLight = Color(0xFFF1F5F9);
    const cardLight = Color(0xFFFFFFFF);
    const textMain = Color(0xFF0F172A);
    const textSub = Color(0xFF475569);
    const borderSubtle = Color(0x1E000000);

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: bgLight,
      primaryColor: accentEmerald,
      colorScheme: const ColorScheme.light(
        primary: accentEmerald,
        secondary: accentPrimary,
        surface: cardLight,
        error: accentRose,
        onPrimary: Colors.white,
        onSurface: textMain,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: bgLight,
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarIconBrightness: Brightness.dark,
          statusBarBrightness: Brightness.light,
        ),
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: true,
        titleTextStyle: TextStyle(
          color: textMain,
          fontSize: 22,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.5,
        ),
        iconTheme: IconThemeData(color: textMain, size: 24),
      ),
      cardTheme: CardThemeData(
        color: cardLight,
        elevation: 1,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: borderSubtle),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: accentEmerald,
          foregroundColor: Colors.white,
          elevation: 2,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          minimumSize: const Size(88, 56),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          textStyle: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.2,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: cardLight,
        hintStyle: const TextStyle(color: Color(0xFF94A3B8), fontSize: 16),
        labelStyle: const TextStyle(color: textSub, fontSize: 16, fontWeight: FontWeight.w500),
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: borderSubtle),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: borderSubtle),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: accentEmerald, width: 2),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: cardLight,
        elevation: 8,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(24),
          side: const BorderSide(color: borderSubtle),
        ),
        titleTextStyle: const TextStyle(
          color: textMain,
          fontSize: 22,
          fontWeight: FontWeight.w800,
        ),
        contentTextStyle: const TextStyle(
          color: textSub,
          fontSize: 16,
          height: 1.4,
        ),
      ),
    );
  }
}

extension ThemeContext on BuildContext {
  bool get isDark => Theme.of(this).brightness == Brightness.dark;
  Color get bgPrimary => isDark ? AppTheme.bgPrimary : const Color(0xFFF1F5F9);
  Color get bgSecondary => isDark ? AppTheme.bgSecondary : const Color(0xFFFFFFFF);
  Color get bgCard => isDark ? AppTheme.bgCard : const Color(0xFFF8FAFC);
  Color get textPrimary => isDark ? AppTheme.textPrimary : const Color(0xFF0F172A);
  Color get textSecondary => isDark ? AppTheme.textSecondary : const Color(0xFF475569);
  Color get borderGlass => isDark ? AppTheme.borderGlass : const Color(0x1E000000);
}
