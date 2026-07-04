import 'log_service.dart';
import 'tts_service.dart';

class SafetyChainService {
  static const String check48h = 'CHECK_48H';
  static const String escalate60h = 'ESCALATE_60H';
  static const String escalate72h = 'ESCALATE_72H';
  static const List<int> checkpoints = [48, 60, 72];

  final LogService log;
  final TtsService tts;

  SafetyChainService({required this.log, required this.tts});

  String stateForHours(int hoursSinceInteraction) {
    if (hoursSinceInteraction >= 72) return escalate72h;
    if (hoursSinceInteraction >= 60) return escalate60h;
    if (hoursSinceInteraction >= 48) return check48h;
    return 'RESET_ON_INTERACTION';
  }

  Future<void> evaluate(int hoursSinceInteraction) async {
    final state = stateForHours(hoursSinceInteraction);
    log.safetyChain(state);
    switch (state) {
      case escalate72h:
        log.wouldNotify();
        await tts.speak('您好，我们有段时间没联系了，家人已收到通知。');
        break;
      case escalate60h:
        await tts.speak('您好，好久没见了，一切都还好吗？');
        break;
      case check48h:
        await tts.speak('您好，最近怎么样？');
        break;
      default:
        break;
    }
  }
}
