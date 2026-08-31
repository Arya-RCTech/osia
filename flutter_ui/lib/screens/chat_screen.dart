import 'dart:math';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/chat_provider.dart';
import '../theme/osia_theme.dart';
import 'widgets/chat_bubble.dart';
import 'widgets/message_input.dart';
import 'widgets/thread_sidebar.dart';
import 'widgets/top_bar.dart';

/// Main chat screen — responsive layout with top bar, bubble list, and input.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final ScrollController _scrollController = ScrollController();
  bool _sidebarOpen = false;

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  bool _isMobile(BuildContext context) {
    return MediaQuery.of(context).size.width < 600;
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ChatProvider>();
    final isMobile = _isMobile(context);

    // Auto-scroll when messages change
    if (provider.messages.isNotEmpty) {
      _scrollToBottom();
    }

    // Main content area (always present)
    final mainContent = Column(
      children: [
        // ── Top bar ──
        Row(
          children: [
            if (!_sidebarOpen || isMobile)
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: IconButton(
                  icon: const Icon(Icons.menu_rounded, size: 20),
                  color: OsiaColors.textMuted,
                  onPressed: () => setState(() => _sidebarOpen = true),
                  tooltip: 'Open threads',
                ),
              ),
            const Expanded(child: TopBar()),
          ],
        ),
        // ── Chat area ──
        Expanded(
          child: _buildChatArea(context, provider),
        ),
        // ── Input ──
        MessageInput(
          enabled: !provider.isGenerating,
          isGenerating: provider.isGenerating,
          supportsThinking: provider.supportsThinking,
          onSend: (text, thinking) {
            provider.sendMessage(text, thinking: thinking);
            _scrollToBottom();
          },
          onStop: () {
            provider.stopGeneration();
          },
        ),
      ],
    );

    return Scaffold(
      backgroundColor: OsiaColors.background,
      body: isMobile
          // Mobile: sidebar overlays on top via Stack
          ? Stack(
              children: [
                mainContent,
                if (_sidebarOpen)
                  ThreadSidebar(
                    isOpen: _sidebarOpen,
                    onToggle: () =>
                        setState(() => _sidebarOpen = false),
                  ),
              ],
            )
          // Desktop: sidebar sits in a Row
          : Row(
              children: [
                ThreadSidebar(
                  isOpen: _sidebarOpen,
                  onToggle: () =>
                      setState(() => _sidebarOpen = !_sidebarOpen),
                ),
                Expanded(child: mainContent),
              ],
            ),
    );
  }

  Widget _buildChatArea(BuildContext context, ChatProvider provider) {
    // If still connecting, show a loader
    if (provider.status == AppStatus.connecting && provider.messages.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(
              color: OsiaColors.accent,
              strokeWidth: 2,
            ),
            SizedBox(height: 16),
            Text(
              'Connecting to Osia backend...',
              style: TextStyle(
                color: OsiaColors.textMuted,
                fontSize: 14,
              ),
            ),
          ],
        ),
      );
    }

    // Empty state
    if (provider.messages.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.auto_awesome_rounded,
              size: 48,
              color: OsiaColors.accent.withValues(alpha: 0.4),
            ),
            const SizedBox(height: 16),
            const Text(
              'Start a conversation',
              style: TextStyle(
                color: OsiaColors.textMuted,
                fontSize: 16,
                fontWeight: FontWeight.w500,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Type a message below to begin',
              style: TextStyle(
                color: OsiaColors.textDim,
                fontSize: 13,
              ),
            ),
          ],
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final chatMaxWidth =
            _computeMaxChatWidth(constraints.maxWidth, constraints.maxHeight);
        final chatPadding = _computeChatPadding(constraints.maxWidth);

        return Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: chatMaxWidth),
            child: ListView.builder(
              controller: _scrollController,
              padding: EdgeInsets.symmetric(
                horizontal: chatPadding,
                vertical: 16,
              ),
              itemCount: provider.messages.length,
              itemBuilder: (context, index) {
                final msg = provider.messages[index];
                final availableWidth =
                    chatMaxWidth - chatPadding * 2;
                final maxBubbleWidth = msg.isUser
                    ? availableWidth * 0.70
                    : availableWidth * 0.80;

                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: ChatBubble(
                    key: ValueKey('${provider.refreshKey}_$index'),
                    message: msg,
                    maxBubbleWidth: maxBubbleWidth,
                  ),
                );
              },
            ),
          ),
        );
      },
    );
  }

  // ── Responsive helpers (ported from the Flet logic) ────────────────────

  double _computeMaxChatWidth(double w, double h) {
    if (w <= 0) w = 800;
    if (h <= 0) h = 600;
    final aspect = w / h;

    if (aspect > 2.2) return min(w * 0.65, 1400);
    if (aspect > 1.9) return min(w * 0.70, 1300);
    if (aspect > 1.5) return min(w * 0.75, 1200);
    if (aspect > 1.2) return min(w * 0.80, 1000);
    return min(w * 0.90, 900);
  }

  double _computeChatPadding(double w) {
    if (w < 480) return 8;
    if (w < 768) return 12;
    return 20;
  }
}
