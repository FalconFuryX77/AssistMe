import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// AssistMe Design System & Theme Tokens.
/// Specially optimized for high contrast, elderly accessibility, and premium native feel.
class AppTheme {
  // Legacy widgets use these tokens directly. Keep them synchronized with the
  // selected mode; widgets that consume them also depend on Theme.of(context)
  // so the new palette is read when MaterialApp rebuilds.
  static bool _darkMode = true;
  static void setDarkMode(bool enabled) => _darkMode = enabled;

  static const Color _darkBgPrimary = Color(0xFF0A0F1D);
  static const Color _darkBgSecondary = Color(0xFF131B2E);
  static const Color _darkBgCard = Color(0xFF1A243B);
  static const Color _darkBgCardElevated = Color(0xFF22304E);
  static const Color _lightBgPrimary = Color(0xFFF1F5F9);
  static const Color _lightBgSecondary = Color(0xFFFFFFFF);
  static const Color _lightBgCard = Color(0xFFF8FAFC);
  static Color get bgPrimary => _darkMode ? _darkBgPrimary : _lightBgPrimary;
  static Color get bgSecondary => _darkMode ? _darkBgSecondary : _lightBgSecondary;
  static Color get bgCard => _darkMode ? _darkBgCard : _lightBgCard;
  static Color get bgCardElevated => _darkMode ? _darkBgCardElevated : _lightBgSecondary;
  
  // Glassmorphic border tokens
  static const Color _darkBorderGlass = Color(0x24FFFFFF);
  static const Color _darkBorderGlassStrong = Color(0x40FFFFFF);
  static const Color _lightBorderGlass = Color(0x1E000000);
  static Color get borderGlass => _darkMode ? _darkBorderGlass : _lightBorderGlass;
  static Color get borderGlassStrong => _darkMode ? _darkBorderGlassStrong : const Color(0x33000000);
  static const Color borderGlow = Color(0x3310B981);

  // Vibrant, high-contrast semantic accents
  static const Color accentPrimary = Color(0xFF6366F1); // Indigo (Helper primary)
  static const Color accentSecondary = Color(0xFF06B6D4); // Cyan (Highlights)
  static const Color accentEmerald = Color(0xFF10B981); // Emerald (Helpee action & call)
  static const Color accentEmeraldGlow = Color(0xFF059669);
  static const Color accentEmeraldAccessible = Color(0xFF047857);
  static const Color accentRose = Color(0xFFEF4444); // Rose/Red (Panic stop, decline, error)
  static const Color accentAmber = Color(0xFFF59E0B); // Amber (Pending status, warnings)

  // Typography contrast tokens (WCAG AAA compliant on dark)
  static const Color _darkTextPrimary = Color(0xFFF9FAFB);
  static const Color _darkTextSecondary = Color(0xFFCBD5E1);
  static const Color _darkTextMuted = Color(0xFF94A3B8);
  static const Color _lightTextPrimary = Color(0xFF0F172A);
  static const Color _lightTextSecondary = Color(0xFF334155);
  static const Color _lightTextMuted = Color(0xFF475569);
  static Color get textPrimary => _darkMode ? _darkTextPrimary : _lightTextPrimary;
  static Color get textSecondary => _darkMode ? _darkTextSecondary : _lightTextSecondary;
  static Color get textMuted => _darkMode ? _darkTextMuted : _lightTextMuted;

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: _darkBgPrimary,
      primaryColor: accentEmerald,
      colorScheme: const ColorScheme.dark(
        primary: accentEmeraldAccessible,
        secondary: accentPrimary,
        surface: _darkBgSecondary,
        error: accentRose,
        onPrimary: Colors.white,
        onSurface: _darkTextPrimary,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: _darkBgPrimary,
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarIconBrightness: Brightness.light,
          statusBarBrightness: Brightness.dark,
        ),
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: true,
        titleTextStyle: TextStyle(
          color: _darkTextPrimary,
          fontSize: 22,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.5,
        ),
        iconTheme: IconThemeData(color: _darkTextPrimary, size: 24),
      ),
      cardTheme: CardThemeData(
        color: _darkBgSecondary,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: _darkBorderGlass),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: accentEmeraldAccessible,
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
          foregroundColor: _darkTextPrimary,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          minimumSize: const Size(88, 54),
          side: const BorderSide(color: _darkBorderGlassStrong, width: 1.5),
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
        fillColor: _darkBgCard,
        hintStyle: const TextStyle(color: _darkTextMuted, fontSize: 16),
        labelStyle: const TextStyle(color: _darkTextSecondary, fontSize: 16, fontWeight: FontWeight.w500),
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: _darkBorderGlass),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: _darkBorderGlass),
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
        backgroundColor: _darkBgSecondary,
        elevation: 8,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(24),
          side: const BorderSide(color: _darkBorderGlassStrong),
        ),
        titleTextStyle: const TextStyle(
          color: _darkTextPrimary,
          fontSize: 22,
          fontWeight: FontWeight.w800,
        ),
        contentTextStyle: const TextStyle(
          color: _darkTextSecondary,
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
        primary: accentEmeraldAccessible,
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
          backgroundColor: accentEmeraldAccessible,
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
  Color get bgPrimary => isDark ? AppTheme._darkBgPrimary : AppTheme._lightBgPrimary;
  Color get bgSecondary => isDark ? AppTheme._darkBgSecondary : AppTheme._lightBgSecondary;
  Color get bgCard => isDark ? AppTheme._darkBgCard : AppTheme._lightBgCard;
  Color get textPrimary => isDark ? AppTheme._darkTextPrimary : AppTheme._lightTextPrimary;
  Color get textSecondary => isDark ? AppTheme._darkTextSecondary : AppTheme._lightTextSecondary;
  Color get textMuted => isDark ? AppTheme._darkTextMuted : AppTheme._lightTextMuted;
  Color get borderGlass => isDark ? AppTheme._darkBorderGlass : AppTheme._lightBorderGlass;
}
