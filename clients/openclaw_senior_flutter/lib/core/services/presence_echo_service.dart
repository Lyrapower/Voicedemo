import 'tts_service.dart';
import 'log_service.dart';

class PresenceEchoService {
  final TtsService tts;
  final LogService log;

  PresenceEchoService({required this.tts, required this.log});

  Future<String> respond(String input) async {
    if (input == '你在吗') {
      log.presenceEcho();
      await tts.speak('我在，我来帮您。');
      return '我在';
    }
    return '陪着你';
  }
}
