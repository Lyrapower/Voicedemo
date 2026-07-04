import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../core/services/log_service.dart';
import '../../core/services/tts_service.dart';

class SafetyScreen extends StatefulWidget {
  final LogService log;
  final TtsService tts;
  final String trigger;

  const SafetyScreen({
    super.key,
    required this.log,
    required this.tts,
    required this.trigger,
  });

  @override
  State<SafetyScreen> createState() => _SafetyScreenState();
}

class _SafetyScreenState extends State<SafetyScreen> {
  bool _calling = false;

  @override
  void initState() {
    super.initState();
    _announce();
  }

  Future<void> _announce() async {
    await widget.tts.speak('好的，我在。需要叫家人吗？');
  }

  Future<void> _callFamily() async {
    setState(() => _calling = true);
    widget.log.wouldCall();
    await widget.tts.speak('正在联系家人，请稍候。');
    // Replace with real family phone number
    final uri = Uri(scheme: 'tel', path: '+1234567890');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    }
    setState(() => _calling = false);
  }

  Future<void> _callEmergency() async {
    widget.log.safetyTrigger();
    await widget.tts.speak('正在拨打急救电话。');
    final uri = Uri(scheme: 'tel', path: '120');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFFF3E0),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 16),
              const Icon(Icons.favorite, size: 48, color: Color(0xFFE53935)),
              const SizedBox(height: 16),
              const Text(
                '我在，别担心',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF333333),
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '触发原因: ${widget.trigger}',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 16, color: Colors.grey),
              ),
              const SizedBox(height: 32),
              ElevatedButton.icon(
                onPressed: _calling ? null : _callFamily,
                icon: const Icon(Icons.phone, size: 28),
                label: const Text('叫家人'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF4A90D9),
                  foregroundColor: Colors.white,
                  minimumSize: const Size(double.infinity, 70),
                  textStyle: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                ),
              ),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: _callEmergency,
                icon: const Icon(Icons.emergency, size: 28),
                label: const Text('急救 120'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFE53935),
                  foregroundColor: Colors.white,
                  minimumSize: const Size(double.infinity, 70),
                  textStyle: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                ),
              ),
              const SizedBox(height: 32),
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text(
                  '我没事，返回',
                  style: TextStyle(fontSize: 18, color: Colors.grey),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
