import 'package:shared_preferences/shared_preferences.dart';

class LogService {
  static const _key = 'openclaw_log';
  late SharedPreferences _prefs;
  final List<String> entries = [];

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    final saved = _prefs.getStringList(_key) ?? [];
    entries.addAll(saved);
  }

  void appStarted() => _log('APP_STARTED');
  void safetyTrigger() => _log('SAFETY_TRIGGER');
  void wouldNotify() => _log('WOULD_NOTIFY');
  void wouldCall() => _log('WOULD_CALL');
  void ttsSpoken() => _log('TTS_SPOKEN');
  void presenceEcho() => _log('PRESENCE_ECHO');
  void verifiedModeBlock(String reason) => _log('VERIFIED_MODE_BLOCK:$reason');
  void safetyChain(String state) => _log('SAFETY_CHAIN:$state');

  void _log(String event) {
    final entry = '${DateTime.now().toIso8601String()} $event';
    entries.add(entry);
    // Keep last 200 entries
    if (entries.length > 200) entries.removeAt(0);
    _prefs.setStringList(_key, entries);
  }

  List<String> recent({int count = 20}) =>
      entries.reversed.take(count).toList();
}
