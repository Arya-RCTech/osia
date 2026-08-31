import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Osia color palette — dark charcoal + orange-amber accents.
class OsiaColors {
  OsiaColors._();

  // Backgrounds
  static const Color background = Color(0xFF0D1117);
  static const Color surface = Color(0xFF161B22);
  static const Color surfaceVariant = Color(0xFF1C2128);
  static const Color topBar = Color(0xFF12171E);

  // Accents
  static const Color accent = Color(0xFFE65100);
  static const Color accentLight = Color(0xFFFF8F00);
  static const Color accentGlow = Color(0x33E65100); // 20% opacity orange

  // Bubbles
  static const Color userBubble = Color(0xCCBF360C); // ~80% Orange-900
  static const Color aiBubbleBg = Color(0x0DFFFFFF); // ~5% white
  static const Color aiBubbleBorder = Color(0x1AFFFFFF); // ~10% white

  // System
  static const Color systemBorder = Color(0x1AE65100);
  static const Color systemBg = Color(0x08FFFFFF);

  // Text
  static const Color textPrimary = Color(0xFFE6EDF3);
  static const Color textSecondary = Color(0xB3E6EDF3); // 70%
  static const Color textMuted = Color(0x80E6EDF3); // 50%
  static const Color textDim = Color(0x66E6EDF3); // 40%

  // Status
  static const Color statusReady = Color(0xFF66BB6A);
  static const Color statusThinking = Color(0xFFFFCA28);
  static const Color statusError = Color(0xFFEF5350);

  // Dividers
  static const Color divider = Color(0x1AFFFFFF);

  // Sidebar
  static const Color sidebarBg = Color(0xFF0A0E14);
  static const Color sidebarHover = Color(0x1AFFFFFF);
  static const Color sidebarActive = Color(0x1AE65100);
}

/// Build the Osia dark theme.
ThemeData buildOsiaTheme() {
  final base = ThemeData.dark(useMaterial3: true);

  final textTheme = GoogleFonts.interTextTheme(base.textTheme).apply(
    bodyColor: OsiaColors.textPrimary,
    displayColor: OsiaColors.textPrimary,
  );

  return base.copyWith(
    scaffoldBackgroundColor: OsiaColors.background,
    colorScheme: const ColorScheme.dark(
      surface: OsiaColors.surface,
      primary: OsiaColors.accent,
      secondary: OsiaColors.accentLight,
      onSurface: OsiaColors.textPrimary,
      onPrimary: Colors.white,
      error: OsiaColors.statusError,
    ),
    textTheme: textTheme,
    iconTheme: const IconThemeData(color: OsiaColors.textSecondary),
    dividerColor: OsiaColors.divider,
    dropdownMenuTheme: DropdownMenuThemeData(
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: OsiaColors.surfaceVariant,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: OsiaColors.divider),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: OsiaColors.divider),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(
            color: OsiaColors.accent.withValues(alpha: 0.6),
          ),
        ),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 8,
        ),
        isDense: true,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: false,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: OsiaColors.divider),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: OsiaColors.divider),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: OsiaColors.accent),
      ),
      hintStyle: const TextStyle(color: OsiaColors.textDim),
    ),
  );
}
