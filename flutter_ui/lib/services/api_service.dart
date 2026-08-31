import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../models/chat_message.dart';

/// HTTP client for all Osia FastAPI backend endpoints.
///
/// Connects to the locally-running backend at [baseUrl].
class ApiService {
  final String baseUrl;
  final http.Client _client;

  ApiService({this.baseUrl = 'http://127.0.0.1:8000'})
      : _client = http.Client();

  // ── Health ─────────────────────────────────────────────────────────────

  /// Check backend health. Returns parsed JSON or null on failure.
  Future<Map<String, dynamic>?> getHealth() async {
    try {
      final resp = await _client
          .get(Uri.parse('$baseUrl/api/v1/health'))
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// Poll until the backend responds with 200, up to [maxWait].
  Future<bool> waitForBackend({
    Duration maxWait = const Duration(seconds: 30),
    Duration interval = const Duration(seconds: 1),
  }) async {
    final deadline = DateTime.now().add(maxWait);
    while (DateTime.now().isBefore(deadline)) {
      final health = await getHealth();
      if (health != null) return true;
      await Future.delayed(interval);
    }
    return false;
  }

  // ── Models ─────────────────────────────────────────────────────────────

  /// Fetch the available model list from models.json (via the backend).
  ///
  /// Returns the list in priority order — the default chat model is first.
  /// Falls back to an empty list on failure so the UI degrades gracefully.
  Future<List<ModelInfo>> listModels() async {
    try {
      final resp = await _client
          .get(Uri.parse('$baseUrl/api/v1/models'))
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode == 200) {
        final list = jsonDecode(resp.body) as List<dynamic>;
        return list
            .map((m) => ModelInfo.fromJson(m as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}
    return [];
  }

  /// Trigger a hot-reload of models.json on the backend without restarting.
  Future<void> reloadModels() async {
    try {
      await _client
          .post(Uri.parse('$baseUrl/api/v1/models/reload'))
          .timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  /// Stop a specific local model and free its resources.
  Future<bool> stopModel(String modelId) async {
    try {
      final resp = await _client
          .post(Uri.parse('$baseUrl/api/v1/models/$modelId/stop'))
          .timeout(const Duration(seconds: 10));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        return data['success'] as bool? ?? false;
      }
    } catch (_) {}
    return false;
  }

  /// Send a message and return the AI response data (response text + optional thread_name).
  Future<Map<String, dynamic>> sendMessage(String message, {String? modelId, bool thinking = false}) async {
    final body = <String, dynamic>{'message': message, 'thinking': thinking};
    if (modelId != null) body['model_id'] = modelId;

    final resp = await _client
        .post(
          Uri.parse('$baseUrl/api/v1/chat'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 120));

    if (resp.statusCode != 200) {
      throw HttpException(
          'Chat failed: ${resp.statusCode} — ${resp.body}');
    }

    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    return {
      'response': data['response'] as String,
      'thread_name': data['thread_name'] as String?,
    };
  }


  /// Stream a message and return AI response data chunks.
  Stream<Map<String, dynamic>> sendMessageStream(String message, {String? modelId, bool thinking = false}) async* {
    final body = <String, dynamic>{'message': message, 'thinking': thinking};
    if (modelId != null) body['model_id'] = modelId;

    final request = http.Request('POST', Uri.parse('$baseUrl/api/v1/chat/stream'))
      ..headers['Content-Type'] = 'application/json'
      ..body = jsonEncode(body);

    final response = await _client.send(request);
    if (response.statusCode != 200) {
      final errorBytes = await response.stream.toBytes();
      throw HttpException('Chat stream failed: ${response.statusCode} — ${utf8.decode(errorBytes)}');
    }

    // SSE parsing
    final lineStream = response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter());

    await for (final line in lineStream) {
      if (line.startsWith('data: ')) {
        final dataStr = line.substring(6).trim();
        if (dataStr.isEmpty) continue;
        try {
          final data = jsonDecode(dataStr) as Map<String, dynamic>;
          yield data;
        } catch (_) {}
      }
    }
  }

  // ── History ────────────────────────────────────────────────────────────

  /// Fetch chat history for a thread.
  Future<List<ChatMessage>> getHistory({
    required int threadId,
    int limit = 50,
  }) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/history?thread_id=$threadId&limit=$limit');
    final resp =
        await _client.get(uri).timeout(const Duration(seconds: 10));

    if (resp.statusCode != 200) {
      throw HttpException('History fetch failed: ${resp.statusCode}');
    }

    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    final messages = data['messages'] as List<dynamic>;
    return messages
        .map((m) => ChatMessage.fromJson(m as Map<String, dynamic>))
        .toList();
  }

  // ── Personas ───────────────────────────────────────────────────────────

  /// List available personas from the backend.
  Future<List<PersonaInfo>> listPersonas() async {
    final resp = await _client
        .get(Uri.parse('$baseUrl/api/v1/personas'))
        .timeout(const Duration(seconds: 5));

    if (resp.statusCode != 200) {
      return [const PersonaInfo(name: 'default', label: 'Default')];
    }

    final list = jsonDecode(resp.body) as List<dynamic>;
    return list
        .map((p) => PersonaInfo.fromJson(p as Map<String, dynamic>))
        .toList();
  }

  /// Switch to a persona by name.
  Future<bool> loadPersona(String personaName) async {
    try {
      final resp = await _client
          .post(
            Uri.parse('$baseUrl/api/v1/personas/load'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'persona_name': personaName}),
          )
          .timeout(const Duration(seconds: 10));
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Proactively trigger model loading on the backend to avoid latency spikes.
  Future<void> preloadModels() async {
    try {
      await _client
          .post(Uri.parse('$baseUrl/api/v1/preload'))
          .timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  // ── Threads ────────────────────────────────────────────────────────────

  /// List all threads.
  Future<List<ThreadInfo>> listThreads() async {
    final resp = await _client
        .get(Uri.parse('$baseUrl/api/v1/threads'))
        .timeout(const Duration(seconds: 5));

    if (resp.statusCode != 200) return [];

    final list = jsonDecode(resp.body) as List<dynamic>;
    return list
        .map((t) => ThreadInfo.fromJson(t as Map<String, dynamic>))
        .toList();
  }

  /// Create a new thread.
  Future<int?> createThread(String name) async {
    try {
      final resp = await _client
          .post(
            Uri.parse('$baseUrl/api/v1/threads/create'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'name': name}),
          )
          .timeout(const Duration(seconds: 10));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        return data['thread_id'] as int?;
      }
    } catch (_) {}
    return null;
  }

  /// Switch to a thread.
  Future<bool> switchThread(int threadId) async {
    try {
      final resp = await _client
          .post(
            Uri.parse('$baseUrl/api/v1/threads/switch'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'thread_id': threadId}),
          )
          .timeout(const Duration(seconds: 10));
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Rename a thread.
  Future<bool> renameThread(int threadId, String newName) async {
    try {
      final resp = await _client
          .post(
            Uri.parse('$baseUrl/api/v1/threads/$threadId/rename'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'name': newName}),
          )
          .timeout(const Duration(seconds: 10));
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Delete a thread and its history.
  Future<bool> deleteThread(int threadId) async {
    try {
      final resp = await _client
          .delete(Uri.parse('$baseUrl/api/v1/threads/$threadId'))
          .timeout(const Duration(seconds: 10));
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  void dispose() => _client.close();
}
