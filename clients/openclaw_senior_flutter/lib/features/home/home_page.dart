import 'package:flutter/material.dart';
import '../../core/services/log_service.dart';
import '../../core/services/tts_service.dart';
import '../safety/safety_screen.dart';
import 'home_controller.dart';

class HomePage extends StatefulWidget {
  final LogService log;

  const HomePage({super.key, required this.log});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage>
    with SingleTickerProviderStateMixin {
  late final AnimationController pulseController;
  late final TtsService tts;
  late final HomeController controller;

  bool _speaking = false;
  String _statusText = '我来帮您';

  @override
  void initState() {
    super.initState();
    tts = TtsService();
    tts.init();
    controller = HomeController(log: widget.log, tts: tts);

    pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    pulseController.dispose();
    tts.stop();
    super.dispose();
  }

  Future<void> _handle(String input) async {
    if (_speaking) return;
    setState(() => _speaking = true);

    final result = await controller.handleTap(input);

    if (!mounted) return;

    if (result == 'SAFETY_FLOW' || result == 'WOULD_CALL' || result == 'VERIFIED_BLOCK') {
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => SafetyScreen(
          log: widget.log,
          tts: tts,
          trigger: input,
        ),
      ));
    } else {
      setState(() => _statusText = result);
    }

    setState(() => _speaking = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFAFAFA),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Presence echo header
              AnimatedBuilder(
                animation: pulseController,
                builder: (context, child) {
                  final glow = 0.85 + (pulseController.value * 0.15);
                  return Opacity(opacity: glow, child: child);
                },
                child: GestureDetector(
                  onTap: () => _handle('你在吗'),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
                    decoration: BoxDecoration(
                      color: const Color(0xFF4A90D9),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '我在',
                          style: TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.w700,
                            color: Colors.white,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _statusText,
                          style: const TextStyle(
                            fontSize: 18,
                            color: Colors.white70,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),

              const SizedBox(height: 20),

              // 你在吗 button
              _BigButton(
                label: '你在吗',
                color: const Color(0xFF4A90D9),
                onTap: () => _handle('你在吗'),
                speaking: _speaking,
              ),

              const SizedBox(height: 20),
              _SectionLabel(label: '紧急 / 需要帮助'),
              const SizedBox(height: 10),

              _BigButton(
                label: '不舒服 / 需要帮助',
                color: const Color(0xFFE53935),
                icon: Icons.favorite_border,
                onTap: () => _handle('不舒服'),
                speaking: _speaking,
              ),
              const SizedBox(height: 10),
              _BigButton(
                label: '叫家人',
                color: const Color(0xFFEF6C00),
                icon: Icons.phone,
                onTap: () => _handle('叫家人'),
                speaking: _speaking,
              ),
              const SizedBox(height: 10),
              _BigButton(
                label: '没药了 / 药 / 保健品',
                color: const Color(0xFF8E24AA),
                icon: Icons.medication_outlined,
                onTap: () => _handle('没药了'),
                speaking: _speaking,
              ),

              const SizedBox(height: 20),
              _SectionLabel(label: '日常'),
              const SizedBox(height: 10),

              _BigButton(
                label: '好 / 一般 / 不太好',
                color: const Color(0xFF43A047),
                onTap: () => _handle('今天怎么样'),
                speaking: _speaking,
              ),
              const SizedBox(height: 10),
              _BigButton(
                label: '想聊天',
                color: const Color(0xFF00ACC1),
                icon: Icons.chat_bubble_outline,
                onTap: () => _handle('想聊天'),
                speaking: _speaking,
              ),
              const SizedBox(height: 10),
              _BigButton(
                label: '今天的提醒 / 今天要做的事',
                color: const Color(0xFF039BE5),
                icon: Icons.checklist,
                onTap: () => _handle('提醒'),
                speaking: _speaking,
              ),
              const SizedBox(height: 10),
              _BigButton(
                label: '今天吃什么',
                color: const Color(0xFF6D4C41),
                icon: Icons.restaurant_outlined,
                onTap: () => _handle('今天吃什么'),
                speaking: _speaking,
              ),

              const SizedBox(height: 20),
              _SectionLabel(label: '其他'),
              const SizedBox(height: 10),

              _BigButton(
                label: 'Wi-Fi断了 / 手机问题',
                color: const Color(0xFF546E7A),
                icon: Icons.wifi_off,
                onTap: () => _handle('手机问题'),
                speaking: _speaking,
              ),
              const SizedBox(height: 10),
              _BigButton(
                label: '翻译 / 视频翻译助手',
                color: const Color(0xFF1565C0),
                icon: Icons.translate,
                onTap: () => _handle('翻译'),
                speaking: _speaking,
              ),
              const SizedBox(height: 30),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String label;
  const _SectionLabel({required this.label});

  @override
  Widget build(BuildContext context) {
    return Text(
      label,
      style: const TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: Color(0xFF888888),
        letterSpacing: 0.5,
      ),
    );
  }
}

class _BigButton extends StatelessWidget {
  final String label;
  final Color color;
  final IconData? icon;
  final VoidCallback onTap;
  final bool speaking;

  const _BigButton({
    required this.label,
    required this.color,
    required this.onTap,
    this.icon,
    this.speaking = false,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 62,
      child: ElevatedButton.icon(
        onPressed: speaking ? null : onTap,
        icon: icon != null
            ? Icon(icon, size: 24, color: Colors.white)
            : const SizedBox.shrink(),
        label: Text(
          label,
          style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w600, color: Colors.white),
        ),
        style: ElevatedButton.styleFrom(
          backgroundColor: color,
          disabledBackgroundColor: color.withOpacity(0.5),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          alignment: Alignment.centerLeft,
          padding: const EdgeInsets.symmetric(horizontal: 20),
        ),
      ),
    );
  }
}
