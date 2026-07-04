import 'log_service.dart';
import 'tts_service.dart';

class VerifiedModeService {
  static const List<String> blockedRiskBuckets = [
    'medication',
    'acute',
    'money',
    'scam',
    'self-harm',
    'suicide',
    'overdose',
    'chest pain',
    "can't breathe",
    'trouble breathing',
  ];

  final LogService log;
  final TtsService tts;

  VerifiedModeService({required this.log, required this.tts});

  bool requiresRedirect(String input) {
    final normalized = input.toLowerCase();
    for (final bucket in blockedRiskBuckets) {
      if (normalized.contains(bucket)) return true;
    }
    return normalized.contains('转钱') ||
        normalized.contains('胸痛') ||
        normalized.contains('喘不过气') ||
        normalized.contains('我想死');
  }

  Future<void> handleHighRisk(String input) async {
    log.verifiedModeBlock(input);
    log.safetyTrigger();
    await tts.speak('这个情况需要家人或医生来帮助您，我来帮您联系。');
  }
}
