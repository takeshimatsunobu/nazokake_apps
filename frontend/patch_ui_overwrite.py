import sys

# 1. main.dart (アプリの根幹・幅制限とテーマカラー) の完全上書き
main_code = """import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_app_check/firebase_app_check.dart';
import 'firebase_options.dart';
import 'screens/main_tab_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  await FirebaseAppCheck.instance.activate(
    webProvider: ReCaptchaEnterpriseProvider('YOUR_RECAPTCHA_SITE_KEY'),
    androidProvider: AndroidProvider.debug,
    appleProvider: AppleProvider.debug,
  );
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '謎掛け学術振興会',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFFF9F9F9),
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF902A19)),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF902A19),
          foregroundColor: Colors.white,
          centerTitle: true,
          elevation: 0,
        ),
        useMaterial3: true,
      ),
      // 💡 PCでもスマホ幅(最大450px)に制限し、中央に配置する
      builder: (context, child) {
        return Container(
          color: Colors.grey[300],
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 450),
              child: ClipRect(child: child),
            ),
          ),
        );
      },
      home: const MainTabScreen(),
    );
  }
}
"""
with open("lib/main.dart", "w", encoding="utf-8") as f:
    f.write(main_code)

# 2. home_screen.dart (カードUIと緑のボタン) の完全上書き
home_code = """import 'package:flutter/material.dart';
import '../services/nazokake_api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final TextEditingController _odaiController = TextEditingController();
  final NazokakeApiService _apiService = NazokakeApiService();
  Stream<NazokakeState>? _taskStream;
  bool _isGenerating = false;

  void _startGeneration() {
    final odai = _odaiController.text.trim();
    if (odai.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _isGenerating = true;
      _taskStream = _apiService.generateNazokake(odai);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('⛩ 謎掛け学術振興会')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            Card(
              elevation: 2,
              color: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  children: [
                    const Text('AIに謎掛けを作らせる', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF902A19))),
                    const SizedBox(height: 24),
                    TextField(
                      controller: _odaiController,
                      decoration: InputDecoration(
                        labelText: 'お題を入力 (例: 大谷翔平)',
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                        filled: true,
                        fillColor: Colors.grey[50],
                      ),
                      enabled: !_isGenerating,
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: ElevatedButton.icon(
                        icon: const Text('🤖', style: TextStyle(fontSize: 18)),
                        label: const Text('お題から生成・鑑定', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF5B8124),
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: _isGenerating ? null : _startGeneration,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),
            if (_taskStream != null)
              StreamBuilder<NazokakeState>(
                stream: _taskStream,
                builder: (context, snapshot) {
                  if (snapshot.hasError) {
                    _isGenerating = false;
                    return Text('通信エラー: ${snapshot.error}', style: const TextStyle(color: Colors.red));
                  }
                  if (!snapshot.hasData) return const CircularProgressIndicator();
                  final state = snapshot.data!;
                  if (state.status == 'completed' && state.result != null) {
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      if (mounted && _isGenerating) setState(() => _isGenerating = false);
                    });
                    return Card(
                      elevation: 4,
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('お題: ${state.result!.hint}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                            const SizedBox(height: 8),
                            Text('解き: ${state.result!.toku}', style: const TextStyle(fontSize: 16)),
                            const SizedBox(height: 8),
                            Text('心は: ${state.result!.kokoro}', style: const TextStyle(fontSize: 16)),
                          ],
                        ),
                      ),
                    );
                  }
                  if (state.status == 'error' || state.status == 'timeout') {
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      if (mounted && _isGenerating) setState(() => _isGenerating = false);
                    });
                    return Text('エラー: ${state.message}', style: const TextStyle(color: Colors.red));
                  }
                  return Column(
                    children: [
                      const CircularProgressIndicator(),
                      const SizedBox(height: 16),
                      Text(state.message, style: const TextStyle(fontSize: 16, color: Colors.blueGrey)),
                    ],
                  );
                },
              ),
          ],
        ),
      ),
    );
  }
}
"""
with open("lib/screens/home_screen.dart", "w", encoding="utf-8") as f:
    f.write(home_code)

print("✅ [SUCCESS] UIデザインの完全上書きに成功しました！")
except Exception as e:
    print(f"🚨 [ERROR] 予期せぬエラー: {e}")
    sys.exit(1)
