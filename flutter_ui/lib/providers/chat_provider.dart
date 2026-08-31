import 'dart:async';
import 'package:flutter/material.dart';
import '../models/chat_message.dart';
import '../services/api_service.dart';

/// Application-wide state manager for Osia chat.
enum AppStatus { ready, thinking, error, connecting }

class ChatProvider extends ChangeNotifier {
  final ApiService _api;

  ChatProvider({ApiService? api}) : _api = api ?? ApiService();

  // ── State ──────────────────────────────────────────────────────────────

  List<ChatMessage> _messages = [];
  List<ChatMessage> get messages => _messages;

  AppStatus _status = AppStatus.connecting;
  AppStatus get status => _status;

  // Available models — fetched from the backend on startup, never hardcoded.
  List<ModelInfo> _availableModels = [];
  List<ModelInfo> get availableModels => _availableModels;

  // Selected model ID — defaults to empty; set from API response on init.
  // The backend always returns defaults.chat_model first, so the first item
  // in _availableModels will be Gemma 4 31B (or whatever is in models.json).
  String _selectedModel = '';
  String get selectedModel => _selectedModel;

  // Default persona is 'default' — overridden by health check on init.
  String _selectedPersona = 'default';
  String get selectedPersona => _selectedPersona;

  List<PersonaInfo> _personas = [
    const PersonaInfo(name: 'default', label: 'Default')
  ];
  List<PersonaInfo> get personas => _personas;

  List<ThreadInfo> _threads = [];
  List<ThreadInfo> get threads => _threads;

  int? _activeThreadId;
  int? get activeThreadId => _activeThreadId;

  String _statusMessage = 'Connecting...';
  String get statusMessage => _statusMessage;

  String _currentModelShort = '';
  String get currentModelShort => _currentModelShort;

  bool _backendReady = false;
  bool get backendReady => _backendReady;

  bool get supportsThinking {
    if (_selectedModel.isEmpty || _availableModels.isEmpty) return false;
    final model = _availableModels.firstWhere(
      (m) => m.id == _selectedModel,
      orElse: () => const ModelInfo(id: '', displayName: ''),
    );
    return model.supportsThinking;
  }

  /// Switch the active model by ID.
  void setModel(String modelId) {
    _selectedModel = modelId;
    _currentModelShort = _availableModels
        .firstWhere((m) => m.id == modelId,
            orElse: () => const ModelInfo(id: '', displayName: ''))
        .displayName;
    notifyListeners();
  }

  bool get isSelectedModelLocal {
    if (_selectedModel.isEmpty || _availableModels.isEmpty) return false;
    final model = _availableModels.firstWhere(
      (m) => m.id == _selectedModel,
      orElse: () => const ModelInfo(id: '', displayName: ''),
    );
    return model.provider.toLowerCase() == 'koboldcpp';
  }

  List<String> _activeLocalModels = [];
  bool get isSelectedModelRunning => _activeLocalModels.contains(_selectedModel);

  Timer? _healthPollingTimer;
  void _startHealthPolling() {
    _healthPollingTimer?.cancel();
    _healthPollingTimer = Timer.periodic(const Duration(seconds: 20), (_) async {
      try {
        final health = await _api.getHealth();
        if (health != null) {
          final dynamic activeLocal = health['active_local_models'];
          if (activeLocal != null && activeLocal is List) {
            final newActive = activeLocal.map((e) => e.toString()).toList();
            // Only notify if there's a change to avoid unnecessary rebuilds
            if (newActive.length != _activeLocalModels.length || 
                !newActive.every((e) => _activeLocalModels.contains(e))) {
              _activeLocalModels = newActive;
              notifyListeners();
            }
          }
        }
      } catch (_) {}
    });
  }

  Future<void> stopLocalModel() async {
    if (_selectedModel.isEmpty) return;
    final modelToStop = _selectedModel;
    _activeLocalModels.remove(modelToStop);
    notifyListeners();
    await _api.stopModel(modelToStop);
  }

  // Key that forces a full widget rebuild when incremented.
  int _refreshKey = 0;
  int get refreshKey => _refreshKey;

  // Throttle timer — prevents per-token notifyListeners() from flooding
  // the Flutter main thread with full rebuilds at 50+ fps.
  // All chunk notifications within a 50ms window are coalesced into one.
  Timer? _streamRebuildTimer;

  void _notifyThrottled() {
    if (_streamRebuildTimer?.isActive ?? false) return; // already pending
    _streamRebuildTimer = Timer(const Duration(milliseconds: 50), () {
      notifyListeners();
    });
  }

  bool _hasPreloaded = false;

  /// Trigger heavy model loading (like fastembed, tokenizers) in the backend once.
  Future<void> triggerPreload() async {
    if (_hasPreloaded || !_backendReady) return;
    _hasPreloaded = true;
    await _api.preloadModels();
  }

  // ── Initialization ─────────────────────────────────────────────────────

  /// Initialize: wait for backend, then fetch models, personas, health, threads, history.
  /// Boots to the last-opened thread, default model = first from API (Gemma 4 31B).
  Future<void> initialize() async {
    _status = AppStatus.connecting;
    _statusMessage = 'Connecting to backend...';
    notifyListeners();

    _backendReady = await _api.waitForBackend();
    if (!_backendReady) {
      _status = AppStatus.error;
      _statusMessage = 'Backend unreachable';
      notifyListeners();
      return;
    }

    // Fetch available models from models.json via the backend.
    // Must happen before personas/health so _selectedModel is valid.
    try {
      _availableModels = await _api.listModels();
      if (_availableModels.isNotEmpty) {
        // API returns defaults.chat_model first — Gemma 4 31B per models.json.
        _selectedModel = _availableModels.first.id;
        _currentModelShort = _shortLabel(_selectedModel);
      }
    } catch (_) {}

    // Fetch personas
    try {
      _personas = await _api.listPersonas();
      // Keep 'default' as the selected persona unless health overrides it.
    } catch (_) {}

    // Fetch threads
    try {
      _threads = await _api.listThreads();
    } catch (_) {
      _threads = [];
    }

    // Fetch health for active thread (the backend knows which thread was last active)
    try {
      final health = await _api.getHealth();
      if (health != null) {
        _activeThreadId = health['active_thread_id'] as int?;
        final personaName = health['active_persona'] as String?;
        if (personaName != null) {
          final match = _personas.where((p) =>
              p.name.toLowerCase() == personaName.toLowerCase() ||
              p.label.toLowerCase() == personaName.toLowerCase());
          if (match.isNotEmpty) {
            _selectedPersona = match.first.name;
          }
        }
        final dynamic activeLocal = health['active_local_models'];
        if (activeLocal != null && activeLocal is List) {
          _activeLocalModels = activeLocal.map((e) => e.toString()).toList();
        }
      }
    } catch (_) {}

    _startHealthPolling();

    // Load chat history for the active thread
    if (_activeThreadId != null) {
      try {
        final history = await _api.getHistory(threadId: _activeThreadId!, limit: 50);
        for (var msg in history) {
          if (msg.role == MessageRole.assistant) {
            _sanitizeHistoryMessage(msg);
          }
        }
        _messages = history;
      } catch (_) {
        _messages = [];
      }
    }

    _status = AppStatus.ready;
    _statusMessage = 'Ready';
    notifyListeners();
  }

  // ── Chat ───────────────────────────────────────────────────────────────

bool _isGenerating = false;
  bool get isGenerating => _isGenerating;

  void _sanitizeHistoryMessage(ChatMessage msg) {
    String tempRaw = msg.content;
    String parsedText = '';
    String parsedThink = '';
    bool inThink = false;
    
    while (tempRaw.isNotEmpty) {
      if (!inThink) {
        final thinkMatch = RegExp(r'<think>').firstMatch(tempRaw);
        final gemmaMatch = RegExp(r'<\|?channel>thought\n?').firstMatch(tempRaw);
        
        int startIdx = -1;
        int tagLength = 0;
        
        if (thinkMatch != null && gemmaMatch != null) {
          if (thinkMatch.start < gemmaMatch.start) {
            startIdx = thinkMatch.start;
            tagLength = thinkMatch.end - thinkMatch.start;
          } else {
            startIdx = gemmaMatch.start;
            tagLength = gemmaMatch.end - gemmaMatch.start;
          }
        } else if (thinkMatch != null) {
          startIdx = thinkMatch.start;
          tagLength = thinkMatch.end - thinkMatch.start;
        } else if (gemmaMatch != null) {
          startIdx = gemmaMatch.start;
          tagLength = gemmaMatch.end - gemmaMatch.start;
        }
        
        if (startIdx != -1) {
          parsedText += tempRaw.substring(0, startIdx);
          inThink = true;
          tempRaw = tempRaw.substring(startIdx + tagLength);
        } else {
          parsedText += tempRaw;
          tempRaw = '';
        }
      } else {
        final thinkEndMatch = RegExp(r'</think>').firstMatch(tempRaw);
        final gemmaEndMatch = RegExp(r'</?channel\|?>').firstMatch(tempRaw);
        
        int endIdx = -1;
        int tagLength = 0;
        
        if (thinkEndMatch != null && gemmaEndMatch != null) {
          if (thinkEndMatch.start < gemmaEndMatch.start) {
            endIdx = thinkEndMatch.start;
            tagLength = thinkEndMatch.end - thinkEndMatch.start;
          } else {
            endIdx = gemmaEndMatch.start;
            tagLength = gemmaEndMatch.end - gemmaEndMatch.start;
          }
        } else if (thinkEndMatch != null) {
          endIdx = thinkEndMatch.start;
          tagLength = thinkEndMatch.end - thinkEndMatch.start;
        } else if (gemmaEndMatch != null) {
          endIdx = gemmaEndMatch.start;
          tagLength = gemmaEndMatch.end - gemmaEndMatch.start;
        }
        
        if (endIdx != -1) {
          parsedThink += tempRaw.substring(0, endIdx);
          inThink = false;
          tempRaw = tempRaw.substring(endIdx + tagLength);
        } else {
          parsedThink += tempRaw;
          tempRaw = '';
        }
      }
    }

    msg.content = parsedText.replaceAll(RegExp(r'\[Just now\]', caseSensitive: false), '').trimLeft();
    if (parsedThink.isNotEmpty) {
      msg.thinkContent = parsedThink.trim();
    }
  }

  void stopGeneration() {
    _isGenerating = false;
    notifyListeners();
  }

  /// Send a user message and stream AI response.
  Future<void> sendMessage(String text, {bool thinking = false}) async {
    if (text.trim().isEmpty) return;

    // Add user message immediately
    _messages.add(ChatMessage(
      content: text,
      role: MessageRole.user,
      timestamp: DateTime.now(),
    ));
    _status = AppStatus.thinking;
    _statusMessage = 'Thinking...';
    _isGenerating = true;
    notifyListeners();

    // Add empty AI message
    final aiMessage = ChatMessage(
      content: '',
      role: MessageRole.assistant,
      timestamp: DateTime.now(),
      isStreaming: true,
    );
    _messages.add(aiMessage);
    
    String rawBuffer = '';

    try {
      final stream = _api.sendMessageStream(text, modelId: _selectedModel, thinking: thinking);
      
      await for (final chunk in stream) {
        if (!_isGenerating) {
          // Cancelled by user
          break;
        }
        
        if (chunk['type'] == 'chunk') {
          final contentStr = chunk['content'] as String;
          rawBuffer += contentStr;
          
          String tempRaw = rawBuffer;
          String parsedText = '';
          String parsedThink = '';
          bool inThink = false;
          
          while (tempRaw.isNotEmpty) {
            if (!inThink) {
              final thinkMatch = RegExp(r'<think>').firstMatch(tempRaw);
              final gemmaMatch = RegExp(r'<\|?channel>thought\n?').firstMatch(tempRaw);
              
              int startIdx = -1;
              int tagLength = 0;
              
              if (thinkMatch != null && gemmaMatch != null) {
                if (thinkMatch.start < gemmaMatch.start) {
                  startIdx = thinkMatch.start;
                  tagLength = thinkMatch.end - thinkMatch.start;
                } else {
                  startIdx = gemmaMatch.start;
                  tagLength = gemmaMatch.end - gemmaMatch.start;
                }
              } else if (thinkMatch != null) {
                startIdx = thinkMatch.start;
                tagLength = thinkMatch.end - thinkMatch.start;
              } else if (gemmaMatch != null) {
                startIdx = gemmaMatch.start;
                tagLength = gemmaMatch.end - gemmaMatch.start;
              }
              
              if (startIdx != -1) {
                parsedText += tempRaw.substring(0, startIdx);
                inThink = true;
                tempRaw = tempRaw.substring(startIdx + tagLength);
              } else {
                parsedText += tempRaw;
                tempRaw = '';
              }
            } else {
              final thinkEndMatch = RegExp(r'</think>').firstMatch(tempRaw);
              final gemmaEndMatch = RegExp(r'</?channel\|?>').firstMatch(tempRaw);
              
              int endIdx = -1;
              int tagLength = 0;
              
              if (thinkEndMatch != null && gemmaEndMatch != null) {
                if (thinkEndMatch.start < gemmaEndMatch.start) {
                  endIdx = thinkEndMatch.start;
                  tagLength = thinkEndMatch.end - thinkEndMatch.start;
                } else {
                  endIdx = gemmaEndMatch.start;
                  tagLength = gemmaEndMatch.end - gemmaEndMatch.start;
                }
              } else if (thinkEndMatch != null) {
                endIdx = thinkEndMatch.start;
                tagLength = thinkEndMatch.end - thinkEndMatch.start;
              } else if (gemmaEndMatch != null) {
                endIdx = gemmaEndMatch.start;
                tagLength = gemmaEndMatch.end - gemmaEndMatch.start;
              }
              
              if (endIdx != -1) {
                parsedThink += tempRaw.substring(0, endIdx);
                inThink = false;
                tempRaw = tempRaw.substring(endIdx + tagLength);
              } else {
                parsedThink += tempRaw;
                tempRaw = '';
              }
            }
          }
          
          aiMessage.content = parsedText.replaceAll(RegExp(r'\[Just now\]', caseSensitive: false), '').trimLeft();
          if (parsedThink.isNotEmpty) {
            aiMessage.thinkContent = parsedThink.trim();
          }
          // Throttled: coalesce rapid chunk updates into one rebuild per 50ms.
          // Without this, a fast local model fires notifyListeners() 50+ times/sec,
          // saturating the Flutter main thread and crashing the app.
          _notifyThrottled();
        } else if (chunk['type'] == 'done') {
          final threadName = chunk['thread_name'] as String?;
          if (threadName != null && _activeThreadId != null) {
            final threadIndex = _threads.indexWhere((t) => t.id == _activeThreadId);
            if (threadIndex >= 0) {
              _threads[threadIndex].name = threadName;
            }
          }
          break;
        } else if (chunk['type'] == 'error') {
          throw Exception(chunk['error']);
        }
      }
    } catch (e) {
      if (aiMessage.content.isEmpty && (aiMessage.thinkContent == null || aiMessage.thinkContent!.isEmpty)) {
        aiMessage.content = 'Error: $e';
        aiMessage.role = MessageRole.system;
      } else {
        aiMessage.content += '\\n\\n[Error: $e]';
      }
      _status = AppStatus.error;
      _statusMessage = 'Error';
    } finally {
      // Cancel any pending throttle timer and do one final flush rebuild.
      _streamRebuildTimer?.cancel();
      _streamRebuildTimer = null;
      _isGenerating = false;
      aiMessage.isStreaming = false;
      _currentModelShort = _shortLabel(_selectedModel);
      _status = AppStatus.ready;
      _statusMessage = 'Ready';
      notifyListeners();
    }
  }

  // ── Model / Persona ────────────────────────────────────────────────────

  void selectModel(String modelValue) {
    _selectedModel = modelValue;
    _currentModelShort = _shortLabel(modelValue);
    notifyListeners();
  }

  /// Derive a compact display string from a model ID.
  String _shortLabel(String modelId) {
    final part = modelId.split('/').last;
    return part.substring(0, part.length.clamp(0, 20));
  }

  Future<void> switchPersona(String personaName) async {
    _status = AppStatus.thinking;
    _statusMessage = 'Switching persona...';
    notifyListeners();

    final success = await _api.loadPersona(personaName);
    if (success) {
      _selectedPersona = personaName;
      final label = _personas
          .firstWhere((p) => p.name == personaName,
              orElse: () => PersonaInfo(name: personaName, label: personaName))
          .label;
      _messages.add(ChatMessage(
        content: '⚡ Switched to $label mode',
        role: MessageRole.system,
        timestamp: DateTime.now(),
      ));
      _status = AppStatus.ready;
      _statusMessage = 'Ready';
    } else {
      _messages.add(ChatMessage(
        content: '❌ Failed to switch persona',
        role: MessageRole.system,
        timestamp: DateTime.now(),
      ));
      _status = AppStatus.error;
      _statusMessage = 'Error';
    }
    notifyListeners();
  }

  // ── Threads ────────────────────────────────────────────────────────────

  /// Switch to a different thread. Loads its history.
  Future<void> switchThread(int threadId) async {
    if (threadId == _activeThreadId) return;

    _status = AppStatus.thinking;
    _statusMessage = 'Loading thread...';
    _messages = [];
    notifyListeners();

    try {
      await _api.switchThread(threadId);
      _activeThreadId = threadId;
      final history = await _api.getHistory(threadId: threadId, limit: 50);
      for (var msg in history) {
        if (msg.role == MessageRole.assistant) {
          _sanitizeHistoryMessage(msg);
        }
      }
      _messages = history;
      _status = AppStatus.ready;
      _statusMessage = 'Ready';
    } catch (e) {
      _status = AppStatus.error;
      _statusMessage = 'Failed to load thread';
    }
    notifyListeners();
  }

  /// Create a new thread with default name, switch to it immediately.
  Future<void> createThread([String name = 'New Chat']) async {
    final newId = await _api.createThread(name);
    if (newId != null) {
      _threads.insert(0, ThreadInfo(
        id: newId,
        name: name,
        createdAt: DateTime.now(),
      ));
      // Switch to the new thread
      _activeThreadId = newId;
      _messages = [];
      try {
        await _api.switchThread(newId);
      } catch (_) {}
      _status = AppStatus.ready;
      _statusMessage = 'Ready';
      notifyListeners();
    }
  }

  /// Rename a thread (local + backend).
  Future<void> renameThread(int threadId, String newName) async {
    final success = await _api.renameThread(threadId, newName);
    if (success) {
      final idx = _threads.indexWhere((t) => t.id == threadId);
      if (idx >= 0) {
        _threads[idx].name = newName;
      }
      notifyListeners();
    }
  }

  /// Delete a thread. If it was active, switch to the first remaining thread.
  Future<void> deleteThread(int threadId) async {
    if (threadId == _activeThreadId) {
      // Can't delete active — switch first
      final other = _threads.firstWhere(
        (t) => t.id != threadId,
        orElse: () => ThreadInfo(id: -1, name: ''),
      );
      if (other.id > 0) {
        await switchThread(other.id);
      } else {
        // Last thread — create a new one first
        await createThread('New Chat');
      }
    }

    final success = await _api.deleteThread(threadId);
    if (success) {
      _threads.removeWhere((t) => t.id == threadId);
      notifyListeners();
    }
  }

  /// Refresh the thread list from the backend.
  Future<void> refreshThreads() async {
    try {
      _threads = await _api.listThreads();
      notifyListeners();
    } catch (_) {}
  }

  // ── Refresh ────────────────────────────────────────────────────────────

  /// Force a full UI repaint by incrementing the key.
  void refreshUI() {
    _refreshKey++;
    notifyListeners();
  }

  // ── Cleanup ────────────────────────────────────────────────────────────

  @override
  void dispose() {
    _streamRebuildTimer?.cancel();
    _api.dispose();
    super.dispose();
  }
}
