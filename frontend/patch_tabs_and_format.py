import os
import sys

# 1. 未実装タブ用のダミー画面（プレースホルダー）を生成
dummy_screens = {
    "self_evaluation_screen.dart": "自作鑑定",
    "grow_evaluation_screen.dart": "評価して育てる",
    "how_to_enjoy_screen.dart": "楽しみ方"
}

for filename, title in dummy_screens.items():
    filepath = f"lib/screens/{filename}"
    content = f"""import 'package:flutter/material.dart';

class {filename.split('_')[0].capitalize()}{filename.split('_')[1].capitalize()}Screen extends StatelessWidget {{
  const {filename.split('_')[0].capitalize()}{filename.split('_')[1].capitalize()}Screen({{super.key}});

  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: AppBar(title: const Text('{title}')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.construction, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text('{title}機能は現在開発中です！', style: const TextStyle(fontSize: 18, color: Colors.grey)),
          ],
        ),
      ),
    );
  }}
}}
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

# 2. 司令塔（main_tab_screen.dart）を5タブ仕様に完全書き換え
main_tab_content = """import 'package:flutter/material.dart';
import 'home_screen.dart';
import 'hall_of_fame_screen.dart';
import 'self_evaluation_screen.dart';
import 'grow_evaluation_screen.dart';
import 'how_to_enjoy_screen.dart';

class MainTabScreen extends StatefulWidget {
  const MainTabScreen({super.key});

  @override
  State<MainTabScreen> createState() => _MainTabScreenState();
}

class _MainTabScreenState extends State<MainTabScreen> {
  int _currentIndex = 0;

  final List<Widget> _screens = [
    const HomeScreen(),
    const SelfEvaluationScreen(),
    const GrowEvaluationScreen(),
    const HallOfFameScreen(),
    const HowToEnjoyScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: _screens,
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) => setState(() => _currentIndex = index),
        type: BottomNavigationBarType.fixed, // 4つ以上のタブを均等に表示するために必須
        selectedItemColor: const Color(0xFF902A19), // 臙脂色
        unselectedItemColor: Colors.grey,
        selectedFontSize: 12,
        unselectedFontSize: 12,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.lightbulb), label: 'AI生成'),
          BottomNavigationBarItem(icon: Icon(Icons.draw), label: '自作鑑定'),
          BottomNavigationBarItem(icon: Icon(Icons.menu_book), label: '評価・育成'),
          BottomNavigationBarItem(icon: Icon(Icons.workspace_premium), label: '殿堂入り'),
          BottomNavigationBarItem(icon: Icon(Icons.help_outline), label: '楽しみ方'),
        ],
      ),
    );
  }
}
"""
with open("lib/screens/main_tab_screen.dart", "w", encoding="utf-8") as f:
    f.write(main_tab_content)

# 3. 殿堂入り画面に「フォーマッター（整形機能）」を注入
hall_of_fame_content = """import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

class HallOfFameScreen extends StatelessWidget {
  const HallOfFameScreen({super.key});

  // 💡 どんなテキストでも強引に美しい3段落に成型するフォーマッター
  String _formatNazokake(String rawText) {
    // 1. 全ての改行を一旦リセット（削除）
    String s = rawText.replaceAll(RegExp(r'[\\r\\n]+'), '');
    
    // 2. キーワードの直後に改行を強制挿入
    s = s.replaceAll(RegExp(r'(とかけて、?|とかけて\\s?)'), 'とかけて、\\n');
    s = s.replaceAll(RegExp(r'(と解く。?|ととく。?|と解く|ととく)'), 'と解く。\\n');
    s = s.replaceAll(RegExp(r'(その心は、?|そのこころは、?|その心は|そのこころは)'), 'その心は、\\n');
    
    return s.trim();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('👑 殿堂入り作品')),
      body: StreamBuilder<QuerySnapshot>(
        stream: FirebaseFirestore.instance.collection('nazokake_items').where('status', isEqualTo: 2).snapshots(),
        builder: (context, snapshot) {
          if (snapshot.hasError) return const Center(child: Text('エラーが発生しました'));
          if (snapshot.connectionState == ConnectionState.waiting) return const Center(child: CircularProgressIndicator());

          final docs = snapshot.data?.docs ?? [];
          if (docs.isEmpty) return const Center(child: Text('殿堂入りの作品はまだありません。'));

          var items = docs.map((d) => d.data() as Map<String, dynamic>).toList();
          items.sort((a, b) {
            final tA = a['timestamp']?.toString() ?? '';
            final tB = b['timestamp']?.toString() ?? '';
            return tB.compareTo(tA);
          });

          return ListView.builder(
            itemCount: items.length,
            itemBuilder: (context, index) {
              final item = items[index];
              // フォーマッターを通してテキストを描画
              final cleanText = _formatNazokake(item['nazokake_text'] ?? 'テキストなし');
              
              return Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                elevation: 1,
                color: const Color(0xFFFDFDFD), // 画像に合わせたほんのり明るい背景
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.workspace_premium, color: Colors.amber, size: 24),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'お題: ${item['A_TITLE'] ?? '不明'}',
                              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                            ),
                          ),
                        ],
                      ),
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 8.0),
                        child: Divider(height: 1, color: Colors.black12),
                      ),
                      Text(
                        cleanText,
                        style: const TextStyle(fontSize: 15, height: 1.6, color: Colors.black87),
                      ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
"""
with open("lib/screens/hall_of_fame_screen.dart", "w", encoding="utf-8") as f:
    f.write(hall_of_fame_content)

print("✅ [SUCCESS] 5タブの復元とフォーマッターの注入が完了しました！")
