import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/chat_provider.dart';
import '../../theme/osia_theme.dart';

/// Top bar with refresh button, status indicator, persona/model dropdowns,
/// and current model label.
class TopBar extends StatefulWidget {
  const TopBar({super.key});

  @override
  State<TopBar> createState() => _TopBarState();
}

class _TopBarState extends State<TopBar> with SingleTickerProviderStateMixin {
  late final AnimationController _refreshSpinController;

  @override
  void initState() {
    super.initState();
    _refreshSpinController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
  }

  @override
  void dispose() {
    _refreshSpinController.dispose();
    super.dispose();
  }

  void _onRefresh(ChatProvider provider) {
    _refreshSpinController.forward(from: 0);
    provider.refreshUI();
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ChatProvider>();

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: 16,
        vertical: 10,
      ),
      decoration: const BoxDecoration(
        color: OsiaColors.topBar,
        border: Border(
          bottom: BorderSide(color: OsiaColors.divider),
        ),
      ),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 12,
        runSpacing: 12,
        children: [
          // Left: Refresh + Status
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildRefreshButton(provider),
              const SizedBox(width: 12),
              _buildStatusIndicator(provider),
            ],
          ),
          
          // Center: Dropdowns
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              _buildPersonaDropdown(provider),
              _buildModelDropdown(provider),
              if (provider.isSelectedModelRunning) _buildStopButton(context, provider),
            ],
          ),
          
          // Right: Model label
          if (provider.currentModelShort.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(right: 8.0),
              child: Text(
                provider.currentModelShort,
                style: const TextStyle(
                  color: OsiaColors.textMuted,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildRefreshButton(ChatProvider provider) {
    return RotationTransition(
      turns: _refreshSpinController,
      child: Material(
        color: Colors.transparent,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: () => _onRefresh(provider),
          hoverColor: OsiaColors.accent.withValues(alpha: 0.1),
          child: Padding(
            padding: const EdgeInsets.all(6),
            child: Icon(
              Icons.refresh_rounded,
              size: 20,
              color: OsiaColors.accent.withValues(alpha: 0.8),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildStatusIndicator(ChatProvider provider) {
    Color dotColor;
    switch (provider.status) {
      case AppStatus.ready:
        dotColor = OsiaColors.statusReady;
        break;
      case AppStatus.thinking:
        dotColor = OsiaColors.statusThinking;
        break;
      case AppStatus.error:
        dotColor = OsiaColors.statusError;
        break;
      case AppStatus.connecting:
        dotColor = OsiaColors.statusThinking;
        break;
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _PulsingDot(color: dotColor, pulse: provider.status == AppStatus.thinking),
        const SizedBox(width: 6),
        Text(
          provider.statusMessage,
          style: const TextStyle(
            color: OsiaColors.textSecondary,
            fontSize: 13,
          ),
        ),
      ],
    );
  }

  Widget _buildPersonaDropdown(ChatProvider provider) {
    return _StyledDropdown(
      label: 'Personality',
      value: provider.selectedPersona,
      items: provider.personas
          .map((p) => DropdownMenuItem(value: p.name, child: Text(p.label)))
          .toList(),
      onChanged: (val) {
        if (val != null) provider.switchPersona(val);
      },
    );
  }

  Widget _buildModelDropdown(ChatProvider provider) {
    final models = provider.availableModels;

    // Guard: if models haven't loaded yet, show a disabled placeholder so the
    // dropdown slot still takes up space and doesn't shift the layout.
    if (models.isEmpty) {
      return _StyledDropdown(
        label: 'Model',
        value: '__loading__',
        items: const [
          DropdownMenuItem(value: '__loading__', child: Text('Loading...')),
        ],
        onChanged: null,
      );
    }

    // Ensure the currently selected value exists in the list.
    // If not (e.g. models.json changed), fall back to the first entry.
    final validValue = models.any((m) => m.id == provider.selectedModel)
        ? provider.selectedModel
        : models.first.id;

    return _StyledDropdown(
      label: 'Model',
      value: validValue,
      items: models
          .map((m) => DropdownMenuItem(value: m.id, child: Text(m.label)))
          .toList(),
      onChanged: (val) {
        if (val != null) provider.setModel(val); 
      },
    );
  }

  Widget _buildStopButton(BuildContext context, ChatProvider provider) {
    return Container(
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        border: Border.all(color: Colors.redAccent.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: IconButton(
        icon: const Icon(Icons.stop_rounded),
        color: Colors.redAccent,
        iconSize: 20,
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints(),
        splashRadius: 18,
        tooltip: 'Unload ${provider.currentModelShort}',
        onPressed: () async {
          final confirm = await showDialog<bool>(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: OsiaColors.surface,
              title: const Text('Unload Model?', style: TextStyle(color: OsiaColors.textPrimary)),
              content: Text(
                'Are you sure you want to unload ${provider.currentModelShort} from memory? This will free up RAM/VRAM.',
                style: const TextStyle(color: OsiaColors.textSecondary),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Cancel', style: TextStyle(color: OsiaColors.textMuted)),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  style: TextButton.styleFrom(foregroundColor: Colors.red),
                  child: const Text('Unload'),
                ),
              ],
            ),
          );
          
          if (confirm == true) {
            await provider.stopLocalModel();
          }
        },
      ),
    );
  }
}

// ── Styled Dropdown ─────────────────────────────────────────────────────────

class _StyledDropdown extends StatelessWidget {
  final String label;
  final String value;
  final List<DropdownMenuItem<String>> items;
  final ValueChanged<String?>? onChanged; // nullable = disabled

  const _StyledDropdown({
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 260),
      child: DropdownButtonFormField<String>(
        initialValue: value,
        items: items,
        onChanged: onChanged,
        dropdownColor: OsiaColors.surfaceVariant,
        style: const TextStyle(
          color: OsiaColors.textPrimary,
          fontSize: 13,
        ),
        icon: const Icon(Icons.arrow_drop_down, color: OsiaColors.textMuted),
        decoration: InputDecoration(
          labelText: label,
          labelStyle: TextStyle(
            fontSize: 11,
            color: OsiaColors.textMuted,
          ),
          filled: true,
          fillColor: OsiaColors.surfaceVariant,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          isDense: true,
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
        ),
      ),
    );
  }
}

// ── Pulsing Status Dot ──────────────────────────────────────────────────────

class _PulsingDot extends StatefulWidget {
  final Color color;
  final bool pulse;

  const _PulsingDot({required this.color, required this.pulse});

  @override
  State<_PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<_PulsingDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    );
    if (widget.pulse) _controller.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(_PulsingDot oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.pulse && !_controller.isAnimating) {
      _controller.repeat(reverse: true);
    } else if (!widget.pulse && _controller.isAnimating) {
      _controller.stop();
      _controller.value = 0;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _controller,
      builder: (_, _) {
        final opacity = widget.pulse ? 0.5 + 0.5 * _controller.value : 1.0;
        return Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: widget.color.withValues(alpha: opacity),
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: widget.color.withValues(alpha: 0.3),
                blurRadius: 4,
              ),
            ],
          ),
        );
      },
    );
  }
}
