import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../providers/chat_provider.dart';
import '../../models/chat_message.dart';
import '../../theme/osia_theme.dart';

/// Fully functional thread sidebar with date grouping, inline rename,
/// context menus, and responsive width (30% desktop / 80% mobile overlay).
class ThreadSidebar extends StatelessWidget {
  final bool isOpen;
  final VoidCallback onToggle;

  const ThreadSidebar({
    super.key,
    required this.isOpen,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    if (!isOpen) return const SizedBox.shrink();

    final screenWidth = MediaQuery.of(context).size.width;
    final isMobile = screenWidth < 600;
    final sidebarWidth = isMobile
        ? screenWidth * 0.80
        : screenWidth * 0.30;

    final sidebar = _SidebarBody(
      width: sidebarWidth,
      onToggle: onToggle,
    );

    // On mobile: overlay on Z-axis
    if (isMobile) {
      return Stack(
        children: [
          // Scrim
          GestureDetector(
            onTap: onToggle,
            child: Container(
              color: Colors.black54,
            ),
          ),
          // Sidebar
          sidebar,
        ],
      );
    }

    // On desktop: inline
    return sidebar;
  }
}

class _SidebarBody extends StatelessWidget {
  final double width;
  final VoidCallback onToggle;

  const _SidebarBody({
    required this.width,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeInOut,
      width: width,
      child: Container(
        width: width,
        decoration: const BoxDecoration(
          color: OsiaColors.sidebarBg,
          border: Border(
            right: BorderSide(color: OsiaColors.divider),
          ),
        ),
        child: Column(
          children: [
            // ── 20% blank space (reserved for dashboard) ──
            _buildDashboardPlaceholder(context),
            // ── New Chat button ──
            _buildNewChatButton(context),
            const SizedBox(height: 4),
            const Divider(color: OsiaColors.divider, height: 1),
            // ── Thread list ──
            Expanded(child: _ThreadList(onToggle: onToggle)),
            // ── Bottom bar with plus icon and collapse ──
            _buildBottomBar(context),
          ],
        ),
      ),
    );
  }

  Widget _buildDashboardPlaceholder(BuildContext context) {
    final height = MediaQuery.of(context).size.height * 0.15;
    return SizedBox(
      height: height.clamp(60.0, 140.0),
      child: Center(
        child: Opacity(
          opacity: 0.15,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.dashboard_customize_outlined,
                size: 28,
                color: OsiaColors.textDim,
              ),
              const SizedBox(height: 4),
              Text(
                'Dashboard',
                style: TextStyle(
                  color: OsiaColors.textDim,
                  fontSize: 10,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 1.2,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildNewChatButton(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: SizedBox(
        width: double.infinity,
        child: TextButton.icon(
          onPressed: () {
            context.read<ChatProvider>().createThread();
          },
          icon: Icon(
            Icons.add_rounded,
            size: 18,
            color: OsiaColors.accent,
          ),
          label: Text(
            'New Chat',
            style: TextStyle(
              color: OsiaColors.accent,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
          style: TextButton.styleFrom(
            backgroundColor: OsiaColors.accent.withValues(alpha: 0.08),
            padding: const EdgeInsets.symmetric(vertical: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildBottomBar(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: const BoxDecoration(
        border: Border(
          top: BorderSide(color: OsiaColors.divider),
        ),
      ),
      child: Row(
        children: [
          // Plus icon — secondary "new chat" shortcut
          _BottomIconButton(
            icon: Icons.add_circle_outline_rounded,
            tooltip: 'New Chat',
            onPressed: () => context.read<ChatProvider>().createThread(),
          ),
          const Spacer(),
          // Collapse sidebar
          _BottomIconButton(
            icon: Icons.chevron_left_rounded,
            tooltip: 'Close sidebar',
            onPressed: onToggle,
          ),
        ],
      ),
    );
  }
}

class _BottomIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;

  const _BottomIconButton({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: Icon(icon, size: 20),
      color: OsiaColors.textMuted,
      onPressed: onPressed,
      tooltip: tooltip,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
      splashRadius: 16,
    );
  }
}

// ── Thread List with Date Grouping ──────────────────────────────────────────

class _ThreadList extends StatelessWidget {
  final VoidCallback onToggle;

  const _ThreadList({required this.onToggle});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ChatProvider>();
    final threads = provider.threads;

    if (threads.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.chat_bubble_outline_rounded,
                size: 36,
                color: OsiaColors.textDim,
              ),
              const SizedBox(height: 12),
              Text(
                'No conversations yet',
                style: TextStyle(
                  color: OsiaColors.textMuted,
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Start a new chat above',
                style: TextStyle(
                  color: OsiaColors.textDim,
                  fontSize: 11,
                ),
              ),
            ],
          ),
        ),
      );
    }

    // Group threads by date
    final groups = _groupThreadsByDate(threads);

    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 6),
      itemCount: groups.length,
      itemBuilder: (context, index) {
        final group = groups[index];
        return _DateGroupSection(
          label: group.label,
          threads: group.threads,
          activeThreadId: provider.activeThreadId,
          onSwitch: (id) => provider.switchThread(id),
          onRename: (id, name) => provider.renameThread(id, name),
          onDelete: (id) => provider.deleteThread(id),
        );
      },
    );
  }

  List<_DateGroup> _groupThreadsByDate(List<ThreadInfo> threads) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final last7Days = today.subtract(const Duration(days: 7));

    final todayThreads = <ThreadInfo>[];
    final yesterdayThreads = <ThreadInfo>[];
    final last7Threads = <ThreadInfo>[];
    final olderThreads = <ThreadInfo>[];

    for (final t in threads) {
      final created = t.createdAt;
      if (created == null) {
        olderThreads.add(t);
        continue;
      }
      final day = DateTime(created.year, created.month, created.day);
      if (!day.isBefore(today)) {
        todayThreads.add(t);
      } else if (!day.isBefore(yesterday)) {
        yesterdayThreads.add(t);
      } else if (!day.isBefore(last7Days)) {
        last7Threads.add(t);
      } else {
        olderThreads.add(t);
      }
    }

    final groups = <_DateGroup>[];
    if (todayThreads.isNotEmpty) {
      groups.add(_DateGroup(label: 'Today', threads: todayThreads));
    }
    if (yesterdayThreads.isNotEmpty) {
      groups.add(_DateGroup(label: 'Yesterday', threads: yesterdayThreads));
    }
    if (last7Threads.isNotEmpty) {
      groups.add(_DateGroup(label: 'Last 7 days', threads: last7Threads));
    }
    if (olderThreads.isNotEmpty) {
      groups.add(_DateGroup(label: 'Older', threads: olderThreads));
    }
    return groups;
  }
}

class _DateGroup {
  final String label;
  final List<ThreadInfo> threads;
  const _DateGroup({required this.label, required this.threads});
}

class _DateGroupSection extends StatelessWidget {
  final String label;
  final List<ThreadInfo> threads;
  final int? activeThreadId;
  final void Function(int) onSwitch;
  final void Function(int, String) onRename;
  final void Function(int) onDelete;

  const _DateGroupSection({
    required this.label,
    required this.threads,
    required this.activeThreadId,
    required this.onSwitch,
    required this.onRename,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 16, top: 12, bottom: 4),
          child: Text(
            label,
            style: TextStyle(
              color: OsiaColors.textDim,
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.0,
            ),
          ),
        ),
        ...threads.map((t) => _ThreadTile(
              thread: t,
              isActive: t.id == activeThreadId,
              onTap: () => onSwitch(t.id),
              onRename: (name) => onRename(t.id, name),
              onDelete: () => onDelete(t.id),
            )),
      ],
    );
  }
}

// ── Thread Tile with Context Menu + Inline Rename ───────────────────────────

class _ThreadTile extends StatefulWidget {
  final ThreadInfo thread;
  final bool isActive;
  final VoidCallback onTap;
  final void Function(String) onRename;
  final VoidCallback onDelete;

  const _ThreadTile({
    required this.thread,
    required this.isActive,
    required this.onTap,
    required this.onRename,
    required this.onDelete,
  });

  @override
  State<_ThreadTile> createState() => _ThreadTileState();
}

class _ThreadTileState extends State<_ThreadTile> {
  bool _isRenaming = false;
  bool _isHovered = false;
  late TextEditingController _renameController;
  late FocusNode _renameFocus;

  @override
  void initState() {
    super.initState();
    _renameController = TextEditingController(text: widget.thread.name);
    _renameFocus = FocusNode();
    _renameFocus.addListener(() {
      // Submit on focus loss
      if (!_renameFocus.hasFocus && _isRenaming) {
        _submitRename();
      }
    });
  }

  @override
  void dispose() {
    _renameController.dispose();
    _renameFocus.dispose();
    super.dispose();
  }

  void _startRename() {
    setState(() {
      _isRenaming = true;
      _renameController.text = widget.thread.name;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _renameFocus.requestFocus();
      _renameController.selection = TextSelection(
        baseOffset: 0,
        extentOffset: _renameController.text.length,
      );
    });
  }

  void _submitRename() {
    final newName = _renameController.text.trim();
    setState(() => _isRenaming = false);
    if (newName.isNotEmpty && newName != widget.thread.name) {
      widget.onRename(newName);
    }
  }

  void _cancelRename() {
    setState(() => _isRenaming = false);
    _renameController.text = widget.thread.name;
  }

  void _showContextMenu(BuildContext context, Offset position) {
    showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx,
        position.dy,
        MediaQuery.of(context).size.width - position.dx,
        MediaQuery.of(context).size.height - position.dy,
      ),
      color: OsiaColors.surfaceVariant,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      items: [
        PopupMenuItem(
          value: 'rename',
          child: Row(
            children: [
              Icon(Icons.edit_outlined, size: 16, color: OsiaColors.textSecondary),
              const SizedBox(width: 10),
              Text('Rename', style: TextStyle(color: OsiaColors.textSecondary, fontSize: 13)),
            ],
          ),
        ),
        PopupMenuItem(
          value: 'delete',
          child: Row(
            children: [
              Icon(Icons.delete_outline_rounded, size: 16, color: Colors.redAccent.shade100),
              const SizedBox(width: 10),
              Text('Delete', style: TextStyle(color: Colors.redAccent.shade100, fontSize: 13)),
            ],
          ),
        ),
      ],
    ).then((value) {
      if (!mounted) return;
      if (value == 'rename') {
        _startRename();
      } else if (value == 'delete') {
        _confirmDelete(context);
      }
    });
  }

  void _confirmDelete(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: OsiaColors.surfaceVariant,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        title: Text(
          'Delete chat?',
          style: TextStyle(color: OsiaColors.textPrimary, fontSize: 16),
        ),
        content: Text(
          'This will permanently delete "${widget.thread.name}" and all its messages.',
          style: TextStyle(color: OsiaColors.textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('Cancel',
                style: TextStyle(color: OsiaColors.textMuted)),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              widget.onDelete();
            },
            child: Text('Delete',
                style: TextStyle(color: Colors.redAccent.shade100)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      child: MouseRegion(
        onEnter: (_) => setState(() => _isHovered = true),
        onExit: (_) => setState(() => _isHovered = false),
        child: GestureDetector(
          onSecondaryTapUp: (details) =>
              _showContextMenu(context, details.globalPosition),
          onLongPress: () {
            // For touch devices — show context at tile center
            final box = context.findRenderObject() as RenderBox;
            final pos = box.localToGlobal(
              Offset(box.size.width * 0.5, box.size.height * 0.5),
            );
            _showContextMenu(context, pos);
          },
          child: Material(
            color: widget.isActive
                ? OsiaColors.sidebarActive
                : (_isHovered ? OsiaColors.sidebarHover : Colors.transparent),
            borderRadius: BorderRadius.circular(8),
            child: InkWell(
              onTap: _isRenaming ? null : widget.onTap,
              borderRadius: BorderRadius.circular(8),
              hoverColor: Colors.transparent, // handled by MouseRegion
              child: Padding(
                padding: const EdgeInsets.symmetric(
                    horizontal: 10, vertical: 9),
                child: Row(
                  children: [
                    Icon(
                      widget.isActive
                          ? Icons.chat_rounded
                          : Icons.chat_bubble_outline_rounded,
                      size: 15,
                      color: widget.isActive
                          ? OsiaColors.accent
                          : OsiaColors.textMuted,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _isRenaming
                          ? _buildRenameField()
                          : Text(
                              widget.thread.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                color: widget.isActive
                                    ? OsiaColors.textPrimary
                                    : OsiaColors.textSecondary,
                                fontSize: 13,
                                fontWeight: widget.isActive
                                    ? FontWeight.w500
                                    : FontWeight.normal,
                              ),
                            ),
                    ),
                    // Overflow menu on hover (desktop)
                    if (_isHovered && !_isRenaming)
                      _HoverMenuButton(
                        onRename: _startRename,
                        onDelete: () => _confirmDelete(context),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildRenameField() {
    return KeyboardListener(
      focusNode: FocusNode(), // outer listener
      onKeyEvent: (event) {
        if (event is KeyDownEvent &&
            event.logicalKey == LogicalKeyboardKey.escape) {
          _cancelRename();
        }
      },
      child: TextField(
        controller: _renameController,
        focusNode: _renameFocus,
        onSubmitted: (_) => _submitRename(),
        style: TextStyle(
          color: OsiaColors.textPrimary,
          fontSize: 13,
        ),
        cursorColor: OsiaColors.accent,
        decoration: InputDecoration(
          isDense: true,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
          filled: true,
          fillColor: OsiaColors.background,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: BorderSide(
                color: OsiaColors.accent.withValues(alpha: 0.5)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: BorderSide(color: OsiaColors.accent),
          ),
        ),
      ),
    );
  }
}

/// Three-dot overflow button that appears on hover.
class _HoverMenuButton extends StatelessWidget {
  final VoidCallback onRename;
  final VoidCallback onDelete;

  const _HoverMenuButton({
    required this.onRename,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 24,
      height: 24,
      child: PopupMenuButton<String>(
        padding: EdgeInsets.zero,
        icon: Icon(
          Icons.more_horiz_rounded,
          size: 16,
          color: OsiaColors.textMuted,
        ),
        color: OsiaColors.surfaceVariant,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8)),
        onSelected: (value) {
          if (value == 'rename') onRename();
          if (value == 'delete') onDelete();
        },
        itemBuilder: (_) => [
          PopupMenuItem(
            value: 'rename',
            height: 36,
            child: Row(
              children: [
                Icon(Icons.edit_outlined, size: 15,
                    color: OsiaColors.textSecondary),
                const SizedBox(width: 8),
                Text('Rename',
                    style: TextStyle(
                        color: OsiaColors.textSecondary, fontSize: 12)),
              ],
            ),
          ),
          PopupMenuItem(
            value: 'delete',
            height: 36,
            child: Row(
              children: [
                Icon(Icons.delete_outline_rounded, size: 15,
                    color: Colors.redAccent.shade100),
                const SizedBox(width: 8),
                Text('Delete',
                    style: TextStyle(
                        color: Colors.redAccent.shade100, fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
