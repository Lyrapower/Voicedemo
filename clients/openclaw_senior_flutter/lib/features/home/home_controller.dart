import '../../core/services/log_service.dart';
import '../../core/services/tts_service.dart';
import '../../core/services/presence_echo_service.dart';
import '../../core/services/verified_mode_service.dart';

class HomeController {
  static const String reassuranceInput = '你在吗';
  static const String reassuranceResponse = '我在';
  static const String reassuranceMode = 'instant response';
  static const List<String> allowedSupportPhrases = [
    '我来帮您',
    '我们一起看看',
    '慢慢来',
    '没关系，我再说一遍',
  ];

  final LogService log;
  final TtsService tts;
  late final PresenceEchoService presenceEcho;
  late final VerifiedModeService verifiedMode;

  HomeController({required this.log, required this.tts}) {
    presenceEcho = PresenceEchoService(tts: tts, log: log);
    verifiedMode = VerifiedModeService(tts: tts, log: log);
  }

  Future<String> handleTap(String input) async {
    if (verifiedMode.requiresRedirect(input)) {
      await verifiedMode.handleHighRisk(input);
      return 'VERIFIED_BLOCK';
    }
    if (input == reassuranceInput) {
      return await presenceEcho.respond(input);
    }
    if (input == '不舒服') {
      log.safetyTrigger();
      await tts.speak('好的，我在。您哪里不舒服？我们一起看看。');
      return 'SAFETY_FLOW';
    }
    if (input == '叫家人') {
      log.wouldCall();
      await tts.speak('好的，马上联系家人。');
      return 'WOULD_CALL';
    }
    if (input == '需要帮助') {
      await tts.speak('我来帮您，慢慢来。');
      return '我来帮您';
    }
    return 'reassurance';
  }
}
