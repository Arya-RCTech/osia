import 'dart:convert';
import 'dart:io';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'providers/chat_provider.dart';
import 'screens/chat_screen.dart';
import 'theme/osia_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const OsiaApp());
}

class OsiaApp extends StatefulWidget {
  const OsiaApp({super.key});

  @override
  State<OsiaApp> createState() => _OsiaAppState();
}

class _OsiaAppState extends State<OsiaApp> {
  Process? _backendProcess;
  late final ChatProvider _chatProvider;
  AppLifecycleListener? _lifecycleListener;

  @override
  void initState() {
    super.initState();
    _chatProvider = ChatProvider();

    // Intercept desktop window close / app exit to guarantee backend shutdown
    _lifecycleListener = AppLifecycleListener(
      onExitRequested: () async {
        await _shutdownBackend();
        return AppExitResponse.exit;
      },
    );

    _startBackendAndInitialize();
  }

  /// Check if an Osia backend instance is already running and healthy on port 8000
  Future<bool> _isBackendRunning() async {
    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(milliseconds: 500);
      final request = await client.getUrl(Uri.parse('http://127.0.0.1:8000/api/v1/health'));
      final response = await request.close();
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Find the backend `api.py` by navigating up from this Flutter project
  /// directory. Works regardless of where the executable is run from because
  /// it resolves from Platform.resolvedExecutable in release mode, or from
  /// the current working directory in debug mode.
  String? _findApiPy() {
    // In debug mode, the working dir is usually the Flutter project root.
    // The backend sits one level up (in "Osia Build 2.0/").
    // Walk up from CWD looking for api.py next to this flutter_ui dir.
    var dir = Directory.current;
    for (var i = 0; i < 5; i++) {
      final candidate = File('${dir.path}${Platform.pathSeparator}backend${Platform.pathSeparator}api.py');
      if (candidate.existsSync()) {
        return candidate.path;
      }
      // Also check parent
      final parentCandidate = File(
        '${dir.parent.path}${Platform.pathSeparator}backend${Platform.pathSeparator}api.py',
      );
      if (parentCandidate.existsSync()) {
        return parentCandidate.path;
      }
      dir = dir.parent;
    }
    return null;
  }

  Future<void> _startBackendAndInitialize() async {
    // 1. Check if backend is already alive on port 8000
    final alreadyRunning = await _isBackendRunning();
    if (alreadyRunning) {
      debugPrint('✅ Backend is already alive on port 8000. Reusing existing instance.');
    } else {
      // 2. Try to find and start the backend
      final apiPath = _findApiPy();
      if (apiPath != null) {
        debugPrint('Starting backend: $apiPath');
        try {
          final apiDir = File(apiPath).parent.path;
          final projectRoot = File(apiDir).parent.path;
          String pythonExe = Platform.isWindows ? 'python' : 'python3';
          
          // Check for local venv (one level up from projectRoot)
          final repoRoot = File(projectRoot).parent.path;
          final venvWin = File('$repoRoot\\venv\\Scripts\\python.exe');
          final venvUnix = File('$repoRoot/venv/bin/python');
          if (Platform.isWindows && venvWin.existsSync()) {
            pythonExe = venvWin.path;
          } else if (!Platform.isWindows && venvUnix.existsSync()) {
            pythonExe = venvUnix.path;
          }

          _backendProcess = await Process.start(
            pythonExe,
            [apiPath],
            workingDirectory: projectRoot,
            mode: ProcessStartMode.normal,
          );
          debugPrint('Backend process started (PID: ${_backendProcess?.pid})');
          
          _backendProcess!.stdout.transform(utf8.decoder).listen((data) {
            debugPrint('Backend: $data');
          });
          _backendProcess!.stderr.transform(utf8.decoder).listen((data) {
            debugPrint('Backend Error: $data');
          });
        } catch (e) {
          debugPrint('Failed to start backend: $e');
        }
      } else {
        debugPrint('api.py not found — assuming backend is running externally.');
      }
    }

    // Initialize the provider (waits for backend to be ready)
    await _chatProvider.initialize();
  }

  /// Gracefully terminate backend processes and release port 8000
  Future<void> _shutdownBackend() async {
    debugPrint('🛑 Shutting down backend and freeing port 8000...');
    // 1. Send shutdown request to FastAPI server if active
    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(milliseconds: 600);
      final request = await client.postUrl(Uri.parse('http://127.0.0.1:8000/api/v1/shutdown'));
      final response = await request.close();
      await response.drain();
    } catch (_) {}

    // 2. Terminate the spawned child process if any
    if (_backendProcess != null) {
      _backendProcess!.kill(ProcessSignal.sigterm);
      await Future.delayed(const Duration(milliseconds: 200));
      _backendProcess!.kill(ProcessSignal.sigkill);
      _backendProcess = null;
    }
  }

  @override
  void dispose() {
    _lifecycleListener?.dispose();
    _shutdownBackend();
    _chatProvider.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: _chatProvider,
      child: MaterialApp(
        title: 'Osia',
        debugShowCheckedModeBanner: false,
        theme: buildOsiaTheme(),
        home: const ChatScreen(),
      ),
    );
  }
}
