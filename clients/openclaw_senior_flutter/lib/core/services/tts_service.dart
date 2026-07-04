import 'package:flutter_tts/flutter_tts.dart';

class TtsService {
  final FlutterTts _tts = FlutterTts();
  bool available = true;

  Future<void> init() async {
    await _tts.setLanguage('zh-CN');
    await _tts.setSpeechRate(0.45);
    await _tts.setVolume(1.0);
    await _tts.setPitch(1.0);
  }

  Future<String> speak(String text) async {
    if (!available) return 'TTS_UNAVAILABLE';
    await _tts.speak(text);
    return 'TTS_SPOKEN:$text';
  }

  Future<void> stop() async {
    await _tts.stop();
  }
}
