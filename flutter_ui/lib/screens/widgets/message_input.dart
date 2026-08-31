import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../providers/chat_provider.dart';
import '../../theme/osia_theme.dart';

/// Chat input area with multi-line text field and send button.
///
/// - Enter → send
/// - Shift+Enter → newline
/// - Disabled while [enabled] is false (during API calls)
class MessageInput extends StatefulWidget {
  final void Function(String text, bool thinking) onSend;
  final VoidCallback? onStop;
  final bool enabled;
  final bool supportsThinking;
  final bool isGenerating;

  const MessageInput({
    super.key,
    required this.onSend,
    this.onStop,
    this.enabled = true,
    this.supportsThinking = false,
    this.isGenerating = false,
  });

  @override
  State<MessageInput> createState() => _MessageInputState();
}

class _MessageInputState extends State<MessageInput> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  bool _hasText = false;
  bool _isThinking = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final hasText = _controller.text.trim().isNotEmpty;
      if (hasText != _hasText) {
        setState(() => _hasText = hasText);
        if (hasText) {
          context.read<ChatProvider>().triggerPreload();
        }
      }
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _send() {
    final text = _controller.text.trim();
    if (text.isEmpty || !widget.enabled) return;
    widget.onSend(text, _isThinking);
    _controller.clear();
    _focusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    double w = size.width;
    double h = size.height;
    if (w <= 0) w = 800;
    if (h <= 0) h = 600;
    final aspect = w / h;
    double maxWidth;
    if (aspect > 2.2) {
      maxWidth = w * 0.65 > 1400 ? 1400 : w * 0.65;
    } else if (aspect > 1.9) {
      maxWidth = w * 0.70 > 1300 ? 1300 : w * 0.70;
    } else if (aspect > 1.5) {
      maxWidth = w * 0.75 > 1200 ? 1200 : w * 0.75;
    } else if (aspect > 1.2) {
      maxWidth = w * 0.80 > 1000 ? 1000 : w * 0.80;
    } else {
      maxWidth = w * 0.90 > 900 ? 900 : w * 0.90;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: const BoxDecoration(
        color: OsiaColors.topBar,
        border: Border(
          top: BorderSide(color: OsiaColors.divider),
        ),
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: CallbackShortcuts(
                  bindings: {
                    const SingleActivator(LogicalKeyboardKey.enter, control: true): _send,
                  },
                  child: TextField(
                    controller: _controller,
                    focusNode: _focusNode,
                    enabled: widget.enabled,
                    maxLines: 6,
                    minLines: 1,
                    autofocus: true,
                    style: const TextStyle(
                      color: OsiaColors.textPrimary,
                      fontSize: 14,
                    ),
                    decoration: InputDecoration(
                      hintText: 'Message Osia... (Ctrl+Enter to send)',
                      hintStyle: TextStyle(
                        color: OsiaColors.textDim,
                      ),
                      filled: false,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 12,
                      ),
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
                        borderSide:
                            const BorderSide(color: OsiaColors.accent),
                      ),
                      disabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                          color: OsiaColors.divider.withValues(alpha: 0.5),
                        ),
                      ),
                    ),
                    cursorColor: OsiaColors.accent,
                    textInputAction: TextInputAction.newline,
                  ),
                ),
              ),
          const SizedBox(width: 10),
          if (widget.supportsThinking)
            Padding(
              padding: const EdgeInsets.only(right: 10, bottom: 4),
              child: FilterChip(
                label: const Text('Think'),
                selected: _isThinking,
                onSelected: widget.enabled ? (val) {
                  setState(() => _isThinking = val);
                } : null,
                selectedColor: OsiaColors.accent.withValues(alpha: 0.2),
                checkmarkColor: OsiaColors.accent,
                labelStyle: TextStyle(
                  color: _isThinking ? OsiaColors.accent : OsiaColors.textDim,
                  fontSize: 12,
                ),
                backgroundColor: Colors.transparent,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                  side: BorderSide(
                    color: _isThinking ? OsiaColors.accent : OsiaColors.divider,
                  ),
                ),
              ),
            ),
          AnimatedOpacity(
            duration: const Duration(milliseconds: 200),
            opacity: (widget.isGenerating || (_hasText && widget.enabled)) ? 1.0 : 0.4,
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: widget.isGenerating 
                    ? widget.onStop 
                    : (_hasText && widget.enabled ? _send : null),
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: (widget.isGenerating || (_hasText && widget.enabled))
                        ? LinearGradient(
                            colors: widget.isGenerating 
                                ? [Colors.redAccent, Colors.red]
                                : [OsiaColors.accent, OsiaColors.accentLight],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          )
                        : null,
                    color: (widget.isGenerating || (_hasText && widget.enabled))
                        ? null
                        : OsiaColors.surfaceVariant,
                  ),
                  child: Icon(
                    widget.isGenerating ? Icons.stop_rounded : Icons.send_rounded,
                    size: 20,
                    color: Colors.white,
                  ),
                ),
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
