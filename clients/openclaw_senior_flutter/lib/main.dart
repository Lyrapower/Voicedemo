import 'package:flutter/material.dart';
import 'core/services/log_service.dart';
import 'features/home/home_page.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final log = LogService();
  await log.init();
  log.appStarted();
  runApp(OpenClawSeniorApp(log: log));
}

class OpenClawSeniorApp extends StatelessWidget {
  final LogService log;
  const OpenClawSeniorApp({super.key, required this.log});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '陪伴助手',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF4A90D9),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        textTheme: const TextTheme(
          bodyLarge: TextStyle(fontSize: 20, height: 1.5),
          bodyMedium: TextStyle(fontSize: 18, height: 1.5),
          labelLarge: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            minimumSize: const Size(double.infinity, 60),
            textStyle: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
        ),
      ),
      home: HomePage(log: log),
    );
  }
}
