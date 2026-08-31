/// Represents a single chat message in the Osia conversation.
enum MessageRole { user, assistant, system }

class ChatMessage {
  String content;
  String? thinkContent;
  MessageRole role;
  final DateTime timestamp;
  bool isStreaming;

  ChatMessage({
    required this.content,
    this.thinkContent,
    required this.role,
    required this.timestamp,
    this.isStreaming = false,
  });

  bool get isUser => role == MessageRole.user;
  bool get isAssistant => role == MessageRole.assistant;
  bool get isSystem => role == MessageRole.system;

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final roleStr = (json['role'] as String).toLowerCase();
    MessageRole role;
    switch (roleStr) {
      case 'user':
        role = MessageRole.user;
      case 'assistant':
        role = MessageRole.assistant;
      default:
        role = MessageRole.system;
    }

    return ChatMessage(
      content: json['content'] as String,
      thinkContent: json['think_content'] as String?,
      role: role,
      timestamp: json['timestamp'] != null
          ? DateTime.tryParse(json['timestamp'] as String) ?? DateTime.now()
          : DateTime.now(),
      isStreaming: false,
    );
  }

  Map<String, dynamic> toJson() => {
        'content': content,
        if (thinkContent != null) 'think_content': thinkContent,
        'role': role.name,
        'timestamp': timestamp.toIso8601String(),
      };
}

/// Model info for the dropdown selector.
///
/// Can be constructed directly or from the backend API response
/// via [ModelInfo.fromJson]. The [label] and [value] getters are aliases for
/// backward compatibility with existing dropdown code.
class ModelInfo {
  final String id;
  final String displayName;
  final String provider;
  final bool supportsThinking;
  final bool isDefault;

  const ModelInfo({
    required this.id,
    required this.displayName,
    this.provider = 'groq',
    this.supportsThinking = false,
    this.isDefault = false,
  });

  /// Alias getters so existing dropdown code using .label / .value keeps working.
  String get label => displayName;
  String get value => id;

  factory ModelInfo.fromJson(Map<String, dynamic> json) {
    return ModelInfo(
      id: json['id'] as String,
      displayName: json['display_name'] as String,
      provider: (json['provider'] as String?) ?? 'groq',
      supportsThinking: (json['supports_thinking'] as bool?) ?? false,
      isDefault: (json['is_default'] as bool?) ?? false,
    );
  }
}

/// Persona info from the backend.
class PersonaInfo {
  final String name;
  final String label;

  const PersonaInfo({required this.name, required this.label});

  factory PersonaInfo.fromJson(Map<String, dynamic> json) {
    return PersonaInfo(
      name: json['name'] as String,
      label: json['label'] as String,
    );
  }
}

/// Thread info from the backend.
class ThreadInfo {
  final int id;
  String name; // mutable for inline rename
  final DateTime? createdAt;

  ThreadInfo({required this.id, required this.name, this.createdAt});

  factory ThreadInfo.fromJson(Map<String, dynamic> json) {
    return ThreadInfo(
      id: json['id'] as int,
      name: json['name'] as String,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'] as String)
          : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'created_at': createdAt?.toIso8601String(),
      };
}
