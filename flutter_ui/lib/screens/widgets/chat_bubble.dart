import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:google_fonts/google_fonts.dart';
import '../../models/chat_message.dart';
import '../../theme/osia_theme.dart';

/// Renders a single chat message bubble.
///
/// - **User**   → orange, right-aligned, bottom-right sharp corner
/// - **AI**     → glass surface with markdown + LaTeX rendering, left-aligned
/// - **System** → centered, subtle, italic
class ChatBubble extends StatefulWidget {
  final ChatMessage message;
  final double maxBubbleWidth;

  const ChatBubble({
    super.key,
    required this.message,
    required this.maxBubbleWidth,
  });

  @override
  State<ChatBubble> createState() => _ChatBubbleState();
}

class _ChatBubbleState extends State<ChatBubble>
    with SingleTickerProviderStateMixin {
  late final AnimationController _animController;
  late final Animation<Offset> _slideAnim;
  late final Animation<double> _fadeAnim;

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 350),
    );
    _slideAnim = Tween<Offset>(
      begin: Offset(widget.message.isUser ? 0.15 : -0.15, 0),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _animController,
      curve: Curves.easeOutCubic,
    ));
    _fadeAnim = CurvedAnimation(
      parent: _animController,
      curve: Curves.easeOut,
    );
    _animController.forward();
  }

  @override
  void dispose() {
    _animController.dispose();
    super.dispose();
  }

  // ── Preprocessing ──────────────────────────────────────────────────────────

  /// Replace bare LaTeX commands (outside $...$ delimiters) with Unicode.
  /// We DON'T strip $...$ here anymore — those are handed to flutter_math_fork.
  static String _preprocessBareLatex(String content) {
    // We only replace bare \command forms that appear OUTSIDE math delimiters.
    // First, temporarily mask $...$ regions so we don't touch them.
    final mathMask = <String>[];
    String masked = content.replaceAllMapped(
      RegExp(r'\$\$[\s\S]+?\$\$|\$[^\$\n]{1,200}\$'),
      (m) {
        final idx = mathMask.length;
        mathMask.add(m.group(0)!);
        return '\x00MATH$idx\x00';
      },
    );

    // Apply replacements only to non-math regions
    const replacements = {
      r'\longleftrightarrow': '⟷',
      r'\Longleftrightarrow': '⟺',
      r'\longrightarrow': '⟶',
      r'\longleftarrow': '⟵',
      r'\Longrightarrow': '⟹',
      r'\Longleftarrow': '⟸',
      r'\rightleftharpoons': '⇌',
      r'\leftrightarrow': '↔',
      r'\Leftrightarrow': '⟺',
      r'\rightarrow': '→',
      r'\leftarrow': '←',
      r'\Rightarrow': '⇒',
      r'\Leftarrow': '⇐',
      r'\updownarrow': '↕',
      r'\uparrow': '↑',
      r'\downarrow': '↓',
      r'\nearrow': '↗',
      r'\searrow': '↘',
      r'\swarrow': '↙',
      r'\nwarrow': '↖',
      r'\to': '→',
      r'\gets': '←',
      r'\approx': '≈',
      r'\infty': '∞',
      r'\times': '×',
      r'\cdot': '·',
      r'\div': '÷',
      r'\neq': '≠',
      r'\leq': '≤',
      r'\geq': '≥',
      r'\pm': '±',
      r'\mp': '∓',
    };
    for (final entry in replacements.entries) {
      masked = masked.replaceAll(entry.key, entry.value);
    }

    // Restore math regions
    for (var i = 0; i < mathMask.length; i++) {
      masked = masked.replaceAll('\x00MATH$i\x00', mathMask[i]);
    }
    return masked;
  }

  // ── Content Segment Parsing ────────────────────────────────────────────────

  /// Top-level split: fenced code blocks vs everything else.
  static List<_Segment> _parseTopSegments(String content) {
    final regex = RegExp(r'```(\w*)\n([\s\S]*?)```', multiLine: true);
    final segments = <_Segment>[];
    int lastEnd = 0;

    for (final match in regex.allMatches(content)) {
      if (match.start > lastEnd) {
        final text = content.substring(lastEnd, match.start).trim();
        if (text.isNotEmpty) segments.add(_TextSegment(text));
      }
      segments.add(_CodeSegment(
        language: match.group(1) ?? '',
        code: match.group(2) ?? '',
      ));
      lastEnd = match.end;
    }

    if (lastEnd < content.length) {
      final text = content.substring(lastEnd).trim();
      if (text.isNotEmpty) segments.add(_TextSegment(text));
    }

    if (segments.isEmpty) segments.add(_TextSegment(content));
    return segments;
  }

  /// Split a text segment into markdown runs and math (inline/display) runs.
  static List<_InlineSegment> _parseMathInText(String text) {
    // Match $$...$$ (display) before $...$ (inline) to avoid greedy errors
    final regex = RegExp(
      r'(\$\$([\s\S]+?)\$\$|\$([^\$\n]{1,300})\$)',
      multiLine: true,
    );
    final parts = <_InlineSegment>[];
    int last = 0;

    for (final m in regex.allMatches(text)) {
      if (m.start > last) {
        parts.add(_MarkdownRun(text.substring(last, m.start)));
      }
      final isDisplay = m.group(0)!.startsWith(r'$$');
      final mathContent =
          isDisplay ? (m.group(2) ?? '').trim() : (m.group(3) ?? '').trim();
      parts.add(_MathRun(mathContent, display: isDisplay));
      last = m.end;
    }
    if (last < text.length) parts.add(_MarkdownRun(text.substring(last)));
    if (parts.isEmpty) parts.add(_MarkdownRun(text));
    return parts;
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final msg = widget.message;
    if (msg.isSystem) return _buildSystemBubble(msg);

    return FadeTransition(
      opacity: _fadeAnim,
      child: SlideTransition(
        position: _slideAnim,
        child: Row(
          mainAxisAlignment:
              msg.isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
          children: [
            ConstrainedBox(
              constraints: BoxConstraints(maxWidth: widget.maxBubbleWidth),
              child: msg.isUser
                  ? _buildUserBubble(msg)
                  : _buildAiBubble(context, msg),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildUserBubble(ChatMessage msg) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: OsiaColors.userBubble,
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(18),
          topRight: Radius.circular(18),
          bottomLeft: Radius.circular(18),
          bottomRight: Radius.circular(4),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.15),
            blurRadius: 6,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: SelectableText(
        msg.content,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 15,
          height: 1.45,
        ),
      ),
    );
  }

  Widget _buildAiBubble(BuildContext context, ChatMessage msg) {
    final processed = _preprocessBareLatex(msg.content);
    final topSegments = _parseTopSegments(processed);

    final bool hasThinking = msg.thinkContent != null && msg.thinkContent!.isNotEmpty;

    return GestureDetector(
      onSecondaryTap: () => _copyToClipboard(context, msg.content),
      onLongPress: () => _copyToClipboard(context, msg.content),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 12), // Standard text alignment, no bubble
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (hasThinking)
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  initiallyExpanded: msg.content.isEmpty,
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(left: 8, bottom: 8),
                  leading: const Icon(Icons.lightbulb_outline, size: 18, color: OsiaColors.textDim),
                  title: Text(
                    'Thinking Process',
                    style: TextStyle(
                      color: OsiaColors.textDim,
                      fontSize: 13,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                  children: [
                    SelectableText(
                      msg.thinkContent!,
                      style: TextStyle(
                        color: OsiaColors.textDim,
                        fontSize: 13,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
            if (msg.content.isNotEmpty || msg.isStreaming)
              ...topSegments.map((seg) {
                if (seg is _CodeSegment) {
                  return _buildCodeBlock(context, seg);
                }
                return _buildTextWithMath(context, (seg as _TextSegment).text);
              }),
            const SizedBox(height: 8),
            if (msg.content.isNotEmpty)
              InkWell(
                onTap: () => _copyToClipboard(context, msg.content),
                borderRadius: BorderRadius.circular(4),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.copy_rounded,
                          size: 14,
                          color: OsiaColors.textMuted.withValues(alpha: 0.8)),
                      const SizedBox(width: 6),
                      Text(
                        'Copy',
                        style: TextStyle(
                          color: OsiaColors.textMuted.withValues(alpha: 0.8),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Renders a text block, splitting out $...$ and $$...$$ as LaTeX widgets.
  Widget _buildTextWithMath(BuildContext context, String text) {
    final parts = _parseMathInText(text);

    // If there's no math at all, use plain MarkdownBody
    if (parts.every((p) => p is _MarkdownRun)) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: MarkdownBody(
          data: text,
          selectable: true,
          extensionSet: md.ExtensionSet.gitHubFlavored,
          styleSheet: _markdownStyleSheet(),
        ),
      );
    }

    // Mixed content: interleave MarkdownBody and Math widgets
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: parts.map((part) {
        if (part is _MathRun) {
          return _buildMathWidget(part);
        }
        final mdText = (part as _MarkdownRun).text.trim();
        if (mdText.isEmpty) return const SizedBox.shrink();
        return Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: MarkdownBody(
            data: mdText,
            selectable: true,
            extensionSet: md.ExtensionSet.gitHubFlavored,
            styleSheet: _markdownStyleSheet(),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildMathWidget(_MathRun run) {
    return Padding(
      padding: EdgeInsets.symmetric(
        vertical: run.display ? 10 : 2,
        horizontal: run.display ? 0 : 0,
      ),
      child: Math.tex(
        run.tex,
        mathStyle: run.display ? MathStyle.display : MathStyle.text,
        textStyle: TextStyle(
          color: OsiaColors.textPrimary,
          fontSize: run.display ? 18 : 15,
        ),
        onErrorFallback: (err) => SelectableText(
          run.tex,
          style: GoogleFonts.jetBrainsMono(
            color: OsiaColors.accentLight,
            fontSize: 13.5,
          ),
        ),
      ),
    );
  }

  Widget _buildCodeBlock(BuildContext context, _CodeSegment seg) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFF131720),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: OsiaColors.divider),
      ),
      child: Stack(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 32, 12, 12),
            child: SelectableText(
              seg.code.trimRight(),
              style: GoogleFonts.jetBrainsMono(
                color: OsiaColors.accentLight,
                fontSize: 13.5,
                height: 1.5,
              ),
            ),
          ),
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: OsiaColors.divider.withValues(alpha: 0.5),
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(7),
                  topRight: Radius.circular(7),
                ),
              ),
              child: Row(
                children: [
                  if (seg.language.isNotEmpty)
                    Text(
                      seg.language,
                      style: TextStyle(
                        color: OsiaColors.textMuted.withValues(alpha: 0.7),
                        fontSize: 11,
                        fontFamily: 'monospace',
                      ),
                    ),
                  const Spacer(),
                  GestureDetector(
                    onTap: () {
                      Clipboard.setData(ClipboardData(text: seg.code));
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Code copied to clipboard'),
                          behavior: SnackBarBehavior.floating,
                          duration: Duration(seconds: 2),
                        ),
                      );
                    },
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.copy_rounded,
                            size: 14,
                            color: OsiaColors.textMuted
                                .withValues(alpha: 0.8)),
                        const SizedBox(width: 4),
                        Text(
                          'Copy',
                          style: TextStyle(
                            color: OsiaColors.textMuted
                                .withValues(alpha: 0.8),
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  MarkdownStyleSheet _markdownStyleSheet() {
    return MarkdownStyleSheet(
      p: const TextStyle(
          color: OsiaColors.textPrimary, fontSize: 15, height: 1.5),
      h1: const TextStyle(
          color: OsiaColors.textPrimary,
          fontSize: 22,
          fontWeight: FontWeight.bold),
      h2: const TextStyle(
          color: OsiaColors.textPrimary,
          fontSize: 19,
          fontWeight: FontWeight.bold),
      h3: const TextStyle(
          color: OsiaColors.textPrimary,
          fontSize: 16,
          fontWeight: FontWeight.w600),
      code: GoogleFonts.jetBrainsMono(
        color: OsiaColors.accentLight,
        fontSize: 13.5,
        backgroundColor: OsiaColors.surfaceVariant,
      ),
      codeblockDecoration: BoxDecoration(
        color: const Color(0xFF131720),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: OsiaColors.divider),
      ),
      codeblockPadding: const EdgeInsets.all(12),
      tableHead: const TextStyle(
          color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
      tableBody:
          const TextStyle(color: OsiaColors.textPrimary, fontSize: 14),
      tableHeadAlign: TextAlign.left,
      tableBorder: TableBorder.all(
        color: OsiaColors.divider,
        borderRadius: BorderRadius.circular(6),
      ),
      tableCellsPadding:
          const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      tableColumnWidth: const FlexColumnWidth(),
      blockquoteDecoration: BoxDecoration(
        border: Border(
          left: BorderSide(
              color: OsiaColors.accent.withValues(alpha: 0.5), width: 3),
        ),
      ),
      blockquotePadding: const EdgeInsets.only(left: 12, top: 4, bottom: 4),
      listBullet:
          const TextStyle(color: OsiaColors.accent, fontSize: 15),
      strong: const TextStyle(
          color: Colors.white, fontWeight: FontWeight.w600),
      em: const TextStyle(
          color: OsiaColors.textSecondary, fontStyle: FontStyle.italic),
      a: const TextStyle(
          color: OsiaColors.accentLight,
          decoration: TextDecoration.underline),
      horizontalRuleDecoration: BoxDecoration(
        border: Border(
            top: BorderSide(color: OsiaColors.divider, width: 1)),
      ),
    );
  }

  void _copyToClipboard(BuildContext context, String content) {
    Clipboard.setData(ClipboardData(text: content));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Copied to clipboard'),
        behavior: SnackBarBehavior.floating,
        duration: Duration(seconds: 2),
      ),
    );
  }

  Widget _buildSystemBubble(ChatMessage msg) {
    return FadeTransition(
      opacity: _fadeAnim,
      child: Center(
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
          decoration: BoxDecoration(
            color: OsiaColors.systemBg,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: OsiaColors.systemBorder),
          ),
          child: Text(
            msg.content,
            style: const TextStyle(
              color: OsiaColors.textMuted,
              fontSize: 12,
              fontStyle: FontStyle.italic,
            ),
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}

// ── Segment models ────────────────────────────────────────────────────────────

abstract class _Segment {}

class _TextSegment extends _Segment {
  final String text;
  _TextSegment(this.text);
}

class _CodeSegment extends _Segment {
  final String language;
  final String code;
  _CodeSegment({required this.language, required this.code});
}

abstract class _InlineSegment {}

class _MarkdownRun extends _InlineSegment {
  final String text;
  _MarkdownRun(this.text);
}

class _MathRun extends _InlineSegment {
  final String tex;
  final bool display;
  _MathRun(this.tex, {required this.display});
}
