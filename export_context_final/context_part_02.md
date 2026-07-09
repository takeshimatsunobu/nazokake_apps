

# ==========================================
# 📄 File: .\frontend\patch_errors.py
# ==========================================
```py
import re
import sys

file_main = "lib/main.dart"
try:
    with open(file_main, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. kIsWeb (Web判定ツール) のインポートを追加
    if "package:flutter/foundation.dart" not in content:
        content = content.replace("import 'package:flutter/material.dart';", "import 'package:flutter/material.dart';\nimport 'package:flutter/foundation.dart';")

    # 2. AppCheckのWeb400エラーを回避 (Webならスキップするロジックに変更)
    pattern = re.compile(r"await\s+FirebaseAppCheck\.instance\.activate\(.*?\);", re.DOTALL)
    new_appcheck = """// Web版ではダミーキーによる400エラーを防ぐためAppCheckをスキップ
  if (!kIsWeb) {
    await FirebaseAppCheck.instance.activate(
      androidProvider: AndroidProvider.debug,
      appleProvider: AppleProvider.debug,
    );
  }"""
    content = pattern.sub(new_appcheck, content)

    # 3. フォント警告の抑制 (システムフォントをフォールバックに指定)
    if "fontFamilyFallback" not in content:
        content = content.replace("scaffoldBackgroundColor:", "fontFamilyFallback: const ['Hiragino Sans', 'Meiryo', 'sans-serif'],\n        scaffoldBackgroundColor:")

    with open(file_main, "w", encoding="utf-8") as f:
        f.write(content)
    
    print("✅ [SUCCESS] エラー撲滅パッチの適用に成功しました！")
except Exception as e:
    print(f"🚨 [ERROR] 予期せぬエラー: {e}")
    sys.exit(1)

```


# ==========================================
# 📄 File: .\frontend\patch_index_html.py
# ==========================================
```py
import re
import sys

file_path = "web/index.html"
try:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 古いJSとCSSの読み込みタグを正規表現で完全削除
    cleaned_content = re.sub(r'<script.*?src=["\'].*?app_final\.js.*?["\'].*?></script>\n?', '', content, flags=re.IGNORECASE)
    cleaned_content = re.sub(r'<link.*?href=["\'].*?style\.css.*?["\'].*?>\n?', '', cleaned_content, flags=re.IGNORECASE)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(cleaned_content)
    
    print("✅ [SUCCESS] index.html から不要なタグの除去に成功しました！")
except Exception as e:
    print(f"🚨 [ERROR] {e}")
    sys.exit(1)

```


# ==========================================
# 📄 File: .\frontend\patch_rollback.py
# ==========================================
```py
import sys

file_main = "lib/main.dart"
try:
    main_code = """import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_app_check/firebase_app_check.dart';
import 'firebase_options.dart';
import 'screens/main_tab_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  
  // 致命的クラッシュを防ぐため、ダミーキーで確実に初期化します（400エラーは安全の証拠として許容）
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
    with open(file_main, "w", encoding="utf-8") as f:
        f.write(main_code)
    print("✅ [SUCCESS] 安定動作するメインコードの復元に成功しました！")
except Exception as e:
    print(f"🚨 [ERROR] {e}")
    sys.exit(1)

```


# ==========================================
# 📄 File: .\frontend\patch_tabs_and_format.py
# ==========================================
```py
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

```


# ==========================================
# 📄 File: .\frontend\patch_ui_overwrite.py
# ==========================================
```py
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

```


# ==========================================
# 📄 File: .\frontend\README.md
# ==========================================
```md
# nazokake_app

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

```


# ==========================================
# 📄 File: .\frontend\admin\admin.js
# ==========================================
```js
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';
let adminUserId = '';
let adminPasscode = '';

function showToast(msg, type='info') {
    const c = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.innerText = msg;
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, 3000);
}

async function loginAdmin() {
    adminUserId = document.getElementById('admin-user').value;
    adminPasscode = document.getElementById('admin-pass').value;
    if(!adminUserId || !adminPasscode) return showToast("⚠️ IDとパスワードを入力してください", "error");
    
    const success = await loadAdminFeed();
    if(success) {
        document.getElementById('login-section').classList.add('hidden');
        document.getElementById('dashboard-section').classList.remove('hidden');
        showToast("🔓 コックピットへようこそ");
        loadSettings();
    }
}

function logoutAdmin() {
    adminUserId = ''; adminPasscode = '';
    document.getElementById('admin-user').value = '';
    document.getElementById('admin-pass').value = '';
    document.getElementById('login-section').classList.remove('hidden');
    document.getElementById('dashboard-section').classList.add('hidden');
    document.getElementById('admin-list').innerHTML = '';
    showToast("🚪 ログアウトしました");
}

// 🎛️ AIエンジンの設定を保存
async function saveSettings() {
    const temp = parseFloat(document.getElementById('setting-temp').value);
    const model = document.getElementById('setting-model').value;
    const prompt = document.getElementById('setting-prompt').value;

    try {
        const res = await fetch(`${API_BASE}/admin/settings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-admin-user': adminUserId,
                'x-admin-pass': adminPasscode
            },
            body: JSON.stringify({
                temperature: temp,
                model_name: model,
                system_prompt: prompt
            })
        });
        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("設定の保存に失敗しました");
        showToast("💾 AIエンジンの設定をシステムに反映しました！");
    } catch (e) {
        showToast(`エラー: ${e.message}`, 'error');
    }
}

// 🎛️ AIエンジンの設定を読み込み
async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/admin/settings`, {
            headers: { 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode }
        });
        if (!res.ok) return;
        const data = await res.json();
        
        if (data.temperature) document.getElementById('setting-temp').value = data.temperature;
        if (data.model_name) document.getElementById('setting-model').value = data.model_name;
        if (data.system_prompt) document.getElementById('setting-prompt').value = data.system_prompt;
    } catch (e) {
        console.error("設定読み込みエラー", e);
    }
}

async function loadAdminFeed() {
    const container = document.getElementById('admin-list');
    container.innerHTML = '<p style="color: #888;">通信中...</p>';
    
    try {
        const res = await fetch(`${API_BASE}/admin/feed`, {
            headers: { 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode }
        });
        if (res.status === 401) {
            adminUserId = ''; adminPasscode = '';
            throw new Error("🔑 認証情報が違います");
        }
        if (!res.ok) throw new Error("データの取得に失敗しました");
        
        const data = await res.json();
        if (!data.items || data.items.length === 0) {
            container.innerHTML = '<p style="color: #aaa;">現在、承認待ちのデータはありません。ユーザーの評価を待ちましょう。</p>';
            return true;
        }
        renderAdminList(data.items);
        return true;
    } catch (e) {
        showToast(`エラー: ${e.message}`, "error");
        container.innerHTML = '<p style="color: #ff4500;">通信エラーが発生しました。</p>';
        return false;
    }
}

// ✍️ レンダリング (お題編集フィールドとIPブロックボタンを追加)
function renderAdminList(items) {
    const container = document.getElementById('admin-list');
    container.innerHTML = '';
    
    items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'item-row';
        row.id = `admin-row-${item.id}`;
        
        const odai = item.odai || item.A_TITLE || "不明";
        const toku = item.result?.toku || "";
        const kokoro = item.result?.kokoro || "";
        const score = item.s_total || item.total_score || 0;
        const comment = item.human_comment || "コメントなし";
        const ipAddress = item.submitter_ip || "不明 (記録前データ)";
        
        row.innerHTML = `
            <div class="item-info">
                <div style="margin-bottom: 8px;">
                    <span style="color:var(--golden); font-size: 0.9rem; font-weight:bold;">【お題】</span><br>
                    <input type="text" id="edit-odai-${item.id}" value="${odai}" class="edit-input edit-odai">
                </div>
                
                <div style="margin-bottom: 5px;">
                    <span style="color:#aaa; font-size: 0.9rem;">解き:</span><br>
                    <input type="text" id="edit-toku-${item.id}" value="${toku}" class="edit-input">
                </div>
                <div>
                    <span style="color:#aaa; font-size: 0.9rem;">心:</span><br>
                    <textarea id="edit-kokoro-${item.id}" class="edit-input" rows="2">${kokoro}</textarea>
                </div>
                
                <div class="item-meta">
                    <span class="score-box">⭐ ユーザー評価: ${score}.0</span><br>
                    <div style="margin-top: 8px; padding-bottom: 8px; border-bottom: 1px dashed #444;">
                        <span style="color: #4CAF50; font-weight: bold;">💬 指導コメント:</span> 
                        <span style="color:#fff;">${comment}</span>
                    </div>
                    <div style="margin-top: 8px;">
                        送信元IP: <span class="ip-box">${ipAddress}</span>
                        ${(ipAddress && ipAddress !== "不明 (記録前データ)" && ipAddress !== "unknown") ? `<button class="btn-ban" onclick="banIpAddress('${ipAddress}')">🚨 このIPをブロック(荒らし対策)</button>` : ''}
                    </div>
                </div>
            </div>
            
            <div class="item-actions">
                <button class="btn-golden" style="background-color: var(--golden); color: black;" onclick="approveAdminItem('${item.id}', 3.0)">🏆 Tier A (殿堂/学習+RAG)</button>
                <button class="btn-golden" style="background-color: #C0C0C0; color: black; margin-top: 8px;" onclick="approveAdminItem('${item.id}', 2.0)">🥇 Tier B (優秀/学習のみ)</button>
                <button class="btn-golden" style="background-color: #CD7F32; color: black; margin-top: 8px;" onclick="approveAdminItem('${item.id}', 1.5)">🥈 Tier C (承認/学習除外)</button>
                <button class="btn-save" style="margin-top: 15px; width: 100%; border: 1px solid #aaa;" onclick="resetEvalItem('${item.id}')">🔄 評価のみリセット (白紙化)</button>
                <button class="btn-delete" style="margin-top: 8px; width: 100%;" onclick="deleteItem('${item.id}')">💣 完全抹殺 (DBから物理削除)</button>
            </div>
        `;
        container.appendChild(row);
    });
}

// 🚨 荒らしIPブロックロジック
async function banIpAddress(ip) {
    if(!confirm(`⚠️ 警告: IPアドレス [ ${ip} ] をブラックリストに登録しますか？
今後のこのIPからの送信はすべて遮断されます。`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/admin/ban_ip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode },
            body: JSON.stringify({ ip_address: ip, reason: "コクピットからの手動ブロック" })
        });

        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("ブロック処理に失敗しました");

        showToast(`🚨 成功: IP [ ${ip} ] をシステムから遮断しました`, "error");
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

async function approveAdminItem(docId, tier) {
    if(!confirm("このデータを本番のAI学習用手本として確定しますか？")) return;
    
    // 🌟 追加: お題の修正も取得
    const finalOdai = document.getElementById(`edit-odai-${docId}`).value;
    const finalToku = document.getElementById(`edit-toku-${docId}`).value;
    const finalKokoro = document.getElementById(`edit-kokoro-${docId}`).value;
    
    try {
        const res = await fetch(`${API_BASE}/admin/approve/${docId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode },
            body: JSON.stringify({ 
                is_golden: tier === 3.0,
                tier: tier, 
                reviewer_id: "admin_takeshi",
                override_odai: finalOdai,
                override_toku: finalToku,
                override_kokoro: finalKokoro
            })
        });

        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("通信エラー");

        showToast("💮 ゴールデンデータとして承認・保存しました！");
        const row = document.getElementById(`admin-row-${docId}`);
        row.style.opacity = '0';
        setTimeout(() => row.remove(), 300);
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

async function deleteItem(docId) {
    if(!confirm("⚠️ 本当にこのデータを破棄しますか？(復元不可)")) return;
    try {
        const res = await fetch(`${API_BASE}/admin/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode },
            body: JSON.stringify({ doc_id: docId })
        });

        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("通信エラー");

        showToast("🗑️ データを破棄しました。");
        const row = document.getElementById(`admin-row-${docId}`);
        row.style.opacity = '0';
        setTimeout(() => row.remove(), 300);
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

async function resetEvalItem(docId) {
    if(!confirm("⚠️ このデータの「人間の評価」を白紙に戻し、再度タイムラインに流しますか？")) return;
    try {
        const res = await fetch(`${API_BASE}/admin/reset_eval/${docId}`, {
            method: 'POST',
            headers: { 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode }
        });
        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("通信エラー");

        showToast("🔄 評価をリセットし、再評価待ちに戻しました。");
        const row = document.getElementById(`admin-row-${docId}`);
        if(row) {
            row.style.opacity = '0';
            setTimeout(() => row.remove(), 300);
        }
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

```


# ==========================================
# 📄 File: .\frontend\admin\index.html
# ==========================================
```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>【管理画面】なぞかけディスカバリー</title>
    <style>
        :root { --bg-dark: #121212; --panel-bg: #1e1e1e; --text-main: #e0e0e0; --accent: #ff4500; --golden: #daa520; }
        body { font-family: 'Helvetica Neue', Arial, sans-serif; background-color: var(--bg-dark); color: var(--text-main); margin: 0; padding: 20px; }
        header { border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 10px; }
        h1 { margin: 0; font-size: 1.8rem; color: var(--text-main); }
        .danger-text { color: var(--accent); font-weight: bold; background: rgba(255,69,0,0.1); padding: 5px 10px; border-radius: 4px; }
        .admin-panel { background: var(--panel-bg); border-radius: 8px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.5); margin-bottom: 20px; }
        
        /* 認証UI */
        .hidden { display: none !important; }
        .login-box { max-width: 400px; margin: 80px auto; background: var(--panel-bg); padding: 40px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.8); text-align: center; border-top: 4px solid var(--golden); }
        .login-box h2 { color: var(--golden); margin-top: 0; margin-bottom: 20px; }
        .login-input { width: 90%; padding: 12px; margin: 10px 0; background: #121212; border: 1px solid #444; color: white; border-radius: 4px; outline: none; }
        .login-input:focus { border-color: var(--golden); }
        .login-btn { width: 95%; padding: 12px; margin-top: 15px; background: var(--golden); color: black; font-size: 1.1rem; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        
        /* パラメータUI */
        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 15px; }
        .setting-group label { display: block; color: var(--golden); font-weight: bold; font-size: 0.9rem; margin-bottom: 5px; }
        .setting-input { width: 100%; padding: 8px; background: #121212; border: 1px solid #444; color: #fff; border-radius: 4px; }
        
        /* データリスト UI */
        .item-row { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; background: #2a2a2a; margin-bottom: 15px; padding: 20px; border-radius: 6px; border-left: 5px solid var(--golden); }
        .item-info { flex: 1; min-width: 300px; }
        .edit-input { width: 95%; background: #121212; color: #fff; border: 1px solid #555; border-radius: 4px; padding: 8px; font-family: inherit; margin-bottom: 8px; outline: none; transition: 0.2s; }
        .edit-input:focus { border-color: var(--golden); box-shadow: 0 0 5px rgba(218, 165, 32, 0.5); }
        .edit-odai { font-size: 1.15rem; font-weight: bold; color: var(--golden); }
        .item-meta { font-size: 0.9rem; color: #aaa; margin-top: 10px; background: #222; padding: 10px; border-radius: 4px; border-left: 3px solid #4CAF50;}
        .score-box { display: inline-block; background: #000; padding: 2px 8px; border-radius: 4px; margin-right: 10px; color: #4CAF50; font-weight: bold;}
        .ip-box { font-family: monospace; background: #111; padding: 2px 6px; border-radius: 3px; }
        
        /* ボタン類 */
        .item-actions { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; min-width: 150px; }
        button { padding: 10px 15px; font-size: 0.95rem; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s; }
        .btn-golden { background-color: var(--golden); color: #000; }
        .btn-golden:hover { filter: brightness(1.2); }
        .btn-delete { background-color: #8b0000; color: #fff; }
        .btn-delete:hover { background-color: #ff0000; }
        .btn-ban { background-color: transparent; border: 1px solid #ff4500; color: #ff4500; padding: 4px 8px; font-size: 0.8rem; margin-left: 10px;}
        .btn-ban:hover { background-color: #ff4500; color: #fff; }
        .btn-save { background-color: #333; color: white; border: 1px solid #555; }
        .btn-save:hover { background-color: #444; border-color: var(--golden); color: var(--golden); }
        .home-link { color: #888; text-decoration: none; font-size: 1rem; border: 1px solid #555; padding: 5px 10px; border-radius: 4px; background: transparent; cursor: pointer;}
        .home-link:hover { background: #333; color: #fff; }

        /* トースト */
        #toast-container { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); z-index: 9999; display: flex; flex-direction: column; gap: 10px; }
        .toast { background: #333; color: white; padding: 12px 24px; border-radius: 30px; font-weight: bold; box-shadow: 0 4px 6px rgba(0,0,0,0.5); border-left: 4px solid var(--golden); animation: fadein 0.3s; }
        .toast.error { border-left-color: var(--accent); }
        @keyframes fadein { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>
    <div id="login-section" class="login-box">
        <h2>🛡️ システム認証</h2>
        <input type="text" id="admin-user" class="login-input" placeholder="ユーザーID">
        <input type="password" id="admin-pass" class="login-input" placeholder="パスワード" onkeypress="if(event.key === 'Enter') loginAdmin()">
        <button class="login-btn" onclick="loginAdmin()">入室する</button>
    </div>

    <div id="dashboard-section" class="hidden">
        <header>
            <h1>🛠️ RLHF データセット管理コックピット</h1>
            <div>
                <span class="danger-text">※取扱注意：ここでの操作は本番AIモデルとDBに直結しています。</span>
                <button onclick="logoutAdmin()" class="home-link">🚪 ログアウト</button>
            </div>
        </header>

        <div class="admin-panel">
            <h2>🎛️ AI生成エンジン 操縦パネル</h2>
            <div class="settings-grid">
                <div class="setting-group">
                    <label>Temperature (温度: 0.0 〜 2.0)</label>
                    <input type="number" id="setting-temp" class="setting-input" step="0.1" value="0.7">
                </div>
                <div class="setting-group">
                    <label>使用モデル (LLM)</label>
                    <select id="setting-model" class="setting-input">
                        <option value="gemini-1.5-pro">Gemini 1.5 Pro (本番推論)</option>
                        <option value="gemini-1.5-flash">Gemini 1.5 Flash (高速検証)</option>
                    </select>
                </div>
            </div>
            <div class="setting-group" style="margin-bottom: 15px;">
                <label>システムプロンプト (微調整)</label>
                <textarea id="setting-prompt" class="setting-input" rows="3">あなたはプロの落語家です。ウィットに富んだ「なぞかけ」を作成してください。</textarea>
            </div>
            <button class="btn-save" onclick="saveSettings()">💾 エンジン設定をバックエンドに反映</button>
        </div>

        <div class="admin-panel">
            <h2>📋 承認待ちデータ (ユーザー評価済)</h2>
            <div id="admin-list">データを読み込んでいます...</div>
        </div>
    </div>
    <div id="toast-container"></div>
    <script src="admin.js"></script>
</body>
</html>
```


# ==========================================
# 📄 File: .\frontend\public\app.js
# ==========================================
```js
let isUserFeedLoaded = false;
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';

let myRadarChart = null;
let isFeedLoaded = false;

// --- UX最適化: 美しいトースト通知システム ---
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    const bg = type === 'warning' ? 'bg-[#902A19]' : 'bg-[#5B8124]';
    toast.className = `${bg} text-white px-6 py-3 rounded-full shadow-lg transform transition-all duration-300 -translate-y-10 opacity-0 flex items-center gap-2 font-bold text-sm pointer-events-auto`;
    
    const icon = type === 'warning' ? '⚠️' : '✅';
    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;

    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.remove('-translate-y-10', 'opacity-0');
    });

    setTimeout(() => {
        toast.classList.add('opacity-0', '-translate-y-2');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function switchTab(tabId) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById('view-' + tabId).classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');

    if (tabId === 'feed' && !isUserFeedLoaded) {
        loadUserFeed();
    }
}

async function loadFeed() {
    const container = document.getElementById('feed-container');
    const loading = document.getElementById('feed-loading');
    
    loading.classList.remove('hidden');



    
    try {
        const res = await fetch(`${API_BASE}/feed`);
        if (!res.ok) throw new Error("データベースからの取得に失敗しました");
        const data = await res.json();
        
        loading.classList.add('hidden');
        isFeedLoaded = true;
        
        const items = data.random || data.top10 || [];
        
        if (items.length === 0) {
            container.innerHTML = '<p class="text-center text-gray-500">まだ作品がありません。AIに生成させてみましょう！</p>';
            return;
        }

        items.forEach((item, index) => {
            renderFeedItem(item, container, index);
        });
        
    } catch (e) {
        loading.classList.add('hidden');
        container.innerHTML = `<p class="text-red-500 text-center p-4 bg-red-50 rounded-lg">エラー: ${e.message}</p>`;
    }
}

function renderFeedItem(item, container, index) {
    const odai = item.odai || item.A_TITLE || "不明";
    const result = item.result || {};
    const scores = item.scores || {};
    const canvasId = `feed-chart-${index}`;
    const totalScore = (item.s_total || 0).toFixed(2);
    
    const toku = result.toku ? result.toku : "（取得中）";
    const kokoro = result.kokoro ? result.kokoro : "（取得中）";

    const html = `
        <div class="bg-white rounded-xl shadow-sm p-5 border border-gray-200">
            <div class="text-center mb-4">
                <span class="inline-block px-3 py-1 bg-gray-100 text-[#902A19] rounded-full text-xs font-bold mb-3 border border-gray-200">お題：${odai}</span>
                <p class="font-bold text-gray-800">「${odai}」とかけて、</p>
                <p class="font-bold text-gray-800">「${toku}」ととく。</p>
                <p class="text-sm text-gray-500 mt-2">そのこころは、</p>
                <p class="font-bold text-[#902A19]">どちらも「${kokoro}」でしょう。</p>
            </div>
            
            <hr class="my-3 border-gray-100">
            
            <div class="flex flex-col md:flex-row items-center justify-between gap-4">
                <div class="w-[150px] h-[150px]">
                    <canvas id="${canvasId}"></canvas>
                </div>
                <div class="flex-1 text-center md:text-left">
                    <p class="text-xs text-gray-400 mb-1">AI分析官の総合評価</p>
                    <p class="text-xl font-bold text-[#902A19]">${totalScore} <span class="text-xs text-gray-500 font-normal">/ 5.0</span></p>
                    <button onclick="showToast('評価機能は準備中です！', 'warning')" class="mt-3 text-xs bg-[#5B8124] text-white px-3 py-1.5 rounded-md hover:bg-[#4a6b1d] transition-colors">
                        ★ この作品を評価する
                    </button>
                </div>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', html);
    
    setTimeout(() => {
        const ctx = document.getElementById(canvasId);
        if(ctx) {
            new Chart(ctx.getContext('2d'), {
                type: 'radar',
                data: {
                    labels: ['意外性', '納得感', '言葉遊び', 'ユーモア', '美しさ'],
                    datasets: [{
                        data: [scores.s1||0, scores.s2||0, scores.s3||0, scores.s4||0, scores.s5||0],
                        backgroundColor: 'rgba(144, 42, 25, 0.1)',
                        borderColor: 'rgba(144, 42, 25, 0.8)',
                        borderWidth: 1,
                        pointRadius: 1
                    }]
                },
                options: {
                    scales: { r: { min: 0, max: 5, ticks: {display: false}, pointLabels: {font: {size: 8}} } },
                    plugins: { legend: { display: false } }
                }
            });
        }
    }, 50);
}

async function startGeneration() {
    const odai = document.getElementById('odaiInput').value.trim();
    // 修正: バリデーションエラー時も alert ではなく、専用のエラーカードで美しく表示
    if (!odai) {
        showError("お題を入力してください！");
        return;
    }

    document.getElementById('generateBtn').disabled = true;
    document.getElementById('result-card').classList.add('hidden');
    document.getElementById('error-card').classList.add('hidden');
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('statusMsg').innerText = "AIがお題を解析中...";

    try {
        const res = await fetch(`${API_BASE}/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ odai: odai })
        });
        
        if (!res.ok) throw new Error("サーバーとの通信に失敗しました");
        const data = await res.json();
        
        pollStatus(data.task_id);
    } catch (e) {
        showError(e.message);
    }
}

async function pollStatus(taskId) {
    try {
        const res = await fetch(`${API_BASE}/status/${taskId}`);
        if (!res.ok) throw new Error("ステータス取得に失敗しました");
        const data = await res.json();

        if (data.status === 'completed' && data.eval_status === 'completed') {
            document.getElementById('loading').classList.add('hidden');
            document.getElementById('generateBtn').disabled = false;
            showResult(data);
        } else if (data.status === 'error' || data.eval_status === 'error') {
            throw new Error(data.message || "評価中にエラーが発生しました");
        } else {
            document.getElementById('statusMsg').innerText = data.message || "AIが鑑定機関に評価を依頼中...";
            setTimeout(() => pollStatus(taskId), 2000);
        }
    } catch (e) {
        showError(e.message);
    }
}

function showResult(data) {
    const result = data.result || {};
    const scores = data.scores || {};
    
    document.getElementById('resHint').innerText = result.hint || "取得エラー";
    document.getElementById('resToku').innerText = result.toku || "取得エラー";
    document.getElementById('resKokoro').innerText = result.kokoro || "取得エラー";
    document.getElementById('resScore').innerText = (data.s_total || 0).toFixed(2);
    document.getElementById('resReasoning').innerText = data.reasoning || "講評なし";
    
    const ctx = document.getElementById('radarChart').getContext('2d');
    const chartData = [
        scores.s1 || 0, scores.s2 || 0, scores.s3 || 0, scores.s4 || 0, scores.s5 || 0
    ];

    if (myRadarChart) myRadarChart.destroy();

    myRadarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: ['意外性', '納得感', '言葉遊び', 'ユーモア', '美しさ'],
            datasets: [{
                label: 'AI鑑定スコア',
                data: chartData,
                backgroundColor: 'rgba(144, 42, 25, 0.2)',
                borderColor: 'rgba(144, 42, 25, 1)',
                pointBackgroundColor: 'rgba(144, 42, 25, 1)',
                borderWidth: 2
            }]
        },
        options: {
            scales: {
                r: {
                    min: 0, max: 5, ticks: { stepSize: 1 },
                    pointLabels: { font: { size: 10 } }
                }
            },
            plugins: { legend: { display: false } }
        }
    });

    document.getElementById('result-card').classList.remove('hidden');
}

function showError(msg) {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('generateBtn').disabled = false;
    const errCard = document.getElementById('error-card');
    errCard.innerText = `🚨 エラー: ${msg}`;
    errCard.classList.remove('hidden');
}

// ==========================================

// ==========================================
// 📜 一般ユーザー向けフィード (道場破り) ロジック
// ==========================================


async function loadUserFeed() {
    const container = document.getElementById('feed-container');
    const loading = document.getElementById('feed-loading');
    if(!container) return;

    container.innerHTML = '';
    loading.classList.remove('hidden');

    try {
        const res = await fetch(`${API_BASE}/feed/items`);
        if (!res.ok) throw new Error("データの取得に失敗しました");
        const data = await res.json();

        loading.classList.add('hidden');
        isUserFeedLoaded = true;

        if (!data.items || data.items.length === 0) {
            container.innerHTML = '<p class="text-center text-gray-500">現在、道場破り可能な新着なぞかけはありません。</p>';
            return;
        }

        data.items.forEach(item => {
            renderRLHFFeedItem(item, container);
        });

    } catch (e) {
        loading.classList.add('hidden');
        showToast(`エラー: ${e.message}`, 'warning');
    }
}

function setRating(docId, score) {
    document.getElementById(`feed-score-${docId}`).value = score;
    const labels = ['出直してこい', 'いまいち', '普通', 'お見事', '座布団一枚！'];
    document.getElementById(`feed-score-label-${docId}`).innerText = `⭐${score}.0 : ${labels[score-1]}`;

    for(let i=1; i<=5; i++) {
        const btn = document.getElementById(`star-${docId}-${i}`);
        if(i <= score) {
            btn.classList.remove('bg-gray-100', 'text-gray-400', 'border-gray-200');
            btn.classList.add('bg-yellow-100', 'text-yellow-600', 'border-yellow-400');
        } else {
            btn.classList.add('bg-gray-100', 'text-gray-400', 'border-gray-200');
            btn.classList.remove('bg-yellow-100', 'text-yellow-600', 'border-yellow-400');
        }
    }
}

function renderRLHFFeedItem(item, container) {
    const docId = item.id;
    const odai = item.odai || item.A_TITLE || "不明";
    let toku = item.result?.toku || "";
    let kokoro = item.result?.kokoro || "";

    if (!toku && !kokoro && item.nazokake_text) {
        const tMatch = item.nazokake_text.match(/かけて、?「?(.*?)」?と[解と]く/);
        const kMatch = item.nazokake_text.match(/その[心こころ]は、?(.*)/);
        toku = tMatch ? tMatch[1] : "";
        kokoro = kMatch ? kMatch[1] : item.nazokake_text;
    }

    const html = `
        <div class="bg-white rounded-xl shadow-md border border-[#902A19] overflow-hidden mb-6 transition-all duration-300" id="feed-card-${docId}">
            <div class="bg-[#902A19] px-4 py-2 text-white flex justify-between items-center">
                <span class="font-bold text-sm">💡 AI生成なぞかけ (ID: ${docId.slice(-6)})</span>
            </div>
            <div class="p-5 space-y-4">
                <div class="space-y-3">
                    <div>
                        <label class="text-xs text-gray-500 font-bold">お題</label>
                        <input type="text" id="feed-odai-${docId}" value="${odai}" class="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-[#902A19] outline-none transition">
                    </div>
                    <div>
                        <label class="text-xs text-gray-500 font-bold">解き</label>
                        <input type="text" id="feed-toku-${docId}" value="${toku}" class="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-[#902A19] outline-none transition">
                    </div>
                    <div>
                        <label class="text-xs text-gray-500 font-bold">心</label>
                        <textarea id="feed-kokoro-${docId}" rows="2" class="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-[#902A19] outline-none transition">${kokoro}</textarea>
                    </div>
                </div>

                <div class="bg-orange-50 rounded-lg p-4 border border-orange-100 space-y-4 mt-2">
                    <div>
                        <label class="text-sm text-orange-800 font-bold flex items-center gap-2 mb-2">
                            <span>1. 総合評価 (5段階)</span>
                            <span id="feed-score-label-${docId}" class="text-orange-600 text-xs bg-white px-2 py-1 rounded border border-orange-200 font-bold">未評価</span>
                        </label>
                        <input type="hidden" id="feed-score-${docId}" value="0">
                        <div class="flex gap-2">
                            ${[1,2,3,4,5].map(i => `
                                <button onclick="setRating('${docId}', ${i})" id="star-${docId}-${i}" class="flex-1 py-2 border border-gray-200 bg-gray-100 text-gray-400 rounded-md font-bold transition duration-200 hover:scale-105">
                                    ⭐ ${i}
                                </button>
                            `).join('')}
                        </div>
                    </div>
                    <div>
                        <label class="text-sm text-orange-800 font-bold">2. 評価コメント (任意)</label>
                        <textarea id="feed-comment-${docId}" rows="2" placeholder="例: 「心」の表現が少し分かりにくい、など" class="w-full px-3 py-2 mt-2 border border-orange-200 rounded text-sm focus:ring-2 focus:ring-orange-400 outline-none transition"></textarea>
                    </div>
                </div>

                <div class="mt-4">
                    <button onclick="submitUserEvaluation('${docId}')" class="w-full bg-[#902A19] text-white py-3 rounded-lg font-bold text-sm hover:bg-[#7a2315] shadow flex justify-center items-center gap-2 transition duration-200 transform hover:-translate-y-1">
                        📤 評価・修正を送信する
                    </button>
                </div>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
}

async function submitUserEvaluation(docId) {
    let score = parseFloat(document.getElementById(`feed-score-${docId}`).value);
    let comment = document.getElementById(`feed-comment-${docId}`).value;

    if (score === 0) {
        showToast("⚠️ まずは総合評価（星1〜5）をクリックして選択してください", "warning");
        return;
    }

    const odai = document.getElementById(`feed-odai-${docId}`).value;
    const toku = document.getElementById(`feed-toku-${docId}`).value;
    const kokoro = document.getElementById(`feed-kokoro-${docId}`).value;

    try {
        const res = await fetch(`${API_BASE}/feed/evaluate/${docId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                odai: odai,
                toku: toku,
                kokoro: kokoro,
                s_total: score,
                human_comment: comment
            })
        });

        if (!res.ok) throw new Error("送信に失敗しました");

        showToast("✨ 評価を送信しました！");
        
        const card = document.getElementById(`feed-card-${docId}`);
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
        setTimeout(() => card.remove(), 300);
        
    } catch (e) {
        showToast(`エラー: ${e.message}`, 'warning');
    }
}

```


# ==========================================
# 📄 File: .\frontend\public\index.html
# ==========================================
```html
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⛩ 謎掛け学術振興会</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="app.js" defer></script>
    <style>
        body { background-color: #F9F9F9; font-family: 'Helvetica Neue', Arial, sans-serif; }
        .theme-bg { background-color: #902A19; }
        .theme-btn { background-color: #5B8124; }
        .theme-btn:hover { background-color: #4a6b1d; }
        .theme-btn:disabled { background-color: #a3b88c; cursor: not-allowed; }
        .tab-btn { color: #888; border-bottom: 2px solid transparent; transition: all 0.3s; }
        .tab-btn.active { color: #902A19; border-bottom-color: #902A19; font-weight: bold; }
        .view-section { display: none; }
        .view-section.active { display: block; }
    </style>
</head>
<body class="text-gray-800 pb-24 relative">
    
    <div id="toast-container" class="fixed top-5 left-1/2 transform -translate-x-1/2 z-[100] flex flex-col gap-2 pointer-events-none"></div>

    <header class="theme-bg text-white text-center py-4 shadow-md sticky top-0 z-50">
        <h1 class="text-xl font-bold tracking-widest">⛩ 謎掛け学術振興会</h1>
    </header>

    <main class="max-w-[800px] mx-auto mt-8 p-4">
        <section id="view-generate" class="view-section active">
            <div class="bg-white rounded-xl shadow-md p-6 border border-gray-100 max-w-[500px] mx-auto">
                <h2 class="text-lg font-bold text-[#902A19] text-center mb-6">AIに謎掛けを作らせる</h2>
                <div class="mb-6">
                    <input type="text" id="odaiInput" placeholder="お題を入力 (例: 大谷翔平)" class="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#902A19]">
                </div>
                <button id="generateBtn" onclick="startGeneration()" class="theme-btn w-full text-white font-bold py-3 px-4 rounded-lg flex items-center justify-center gap-2">
                    <span class="text-xl">🤖</span> お題から生成・鑑定
                </button>
            </div>
            <div id="loading" class="mt-8 text-center hidden">
                <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-[#902A19] mx-auto mb-4"></div>
                <p id="statusMsg" class="text-gray-500 font-medium animate-pulse">AIがなぞかけを生成中...</p>
            </div>
            <div id="error-card" class="mt-8 bg-red-50 text-red-600 rounded-xl p-4 hidden border border-red-200 text-center max-w-[500px] mx-auto"></div>
            <div id="result-card" class="mt-8 bg-white rounded-xl shadow-lg p-6 border-t-4 border-[#902A19] hidden max-w-[600px] mx-auto">
                <div class="text-center mb-6">
                    <p class="text-xl font-bold mb-2">「<span id="resHint" class="text-[#902A19]"></span>」とかけて、</p>
                    <p class="text-xl font-bold mb-2">「<span id="resToku" class="text-[#5B8124]"></span>」ととく。</p>
                    <p class="text-lg text-gray-600 mb-2">そのこころは、</p>
                    <p class="text-xl font-bold">どちらも「<span id="resKokoro" class="text-[#902A19]"></span>」でしょう。</p>
                </div>
                <hr class="my-6 border-gray-200">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div class="flex items-center justify-center">
                        <canvas id="radarChart" width="250" height="250"></canvas>
                    </div>
                    <div class="bg-pink-50 p-4 rounded-lg border border-pink-100 flex flex-col justify-center">
                        <p class="font-bold text-[#902A19] text-center text-sm mb-3">💡 AI分析官の講評</p>
                        <p id="resReasoning" class="text-sm text-gray-700 leading-relaxed mb-4"></p>
                        <div class="text-center">
                            <span class="text-xs text-gray-500">総合評価: </span>
                            <span id="resScore" class="text-2xl font-bold text-[#902A19]">0.0</span>
                            <span class="text-sm text-gray-500">/5.0</span>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <section id="view-feed" class="view-section">
            <h2 class="text-xl font-bold text-[#902A19] text-center mb-6 flex items-center justify-center gap-2">
                <span class="text-2xl">📜</span> 評価して育てる（新着作品）
            </h2>
            <div id="feed-loading" class="text-center py-8 hidden">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-[#902A19] mx-auto mb-4"></div>
                <p class="text-gray-500 text-sm">AI道場のデータベースから最新の作品を取得中...</p>
            </div>
            <div id="feed-container" class="space-y-6 max-w-[600px] mx-auto"></div>
        </section>

        <section id="view-admin" class="view-section">
            <h2 class="text-xl font-bold text-[#902A19] text-center mb-6 flex items-center justify-center gap-2">
                <span class="text-2xl">🛡️</span> RLHF 確定コンソール
            </h2>
            <div id="admin-loading" class="text-center py-8 hidden">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-[#902A19] mx-auto mb-4"></div>
                <p class="text-gray-500 text-sm">審査待ちデータを取得中...</p>
            </div>
            <div id="admin-container" class="space-y-6 max-w-[800px] mx-auto">
                </div>
        </section>

    </main>

    <nav class="fixed bottom-0 w-full bg-white border-t border-gray-200 flex justify-around items-center py-2 z-50 shadow-[0_-2px_10px_rgba(0,0,0,0.05)]">
        <button onclick="switchTab('generate')" id="tab-generate" class="tab-btn active flex flex-col items-center w-1/3 py-1">
            <span class="text-xl mb-1">💡</span><span class="text-[10px] font-bold">AI生成</span>
        </button>
        <button onclick="switchTab('feed')" id="tab-feed" class="tab-btn flex flex-col items-center w-1/3 py-1">
            <span class="text-xl mb-1">📜</span><span class="text-[10px] font-bold">評価して育てる</span>
        </button>
    </nav>
</body>
</html>

```


# ==========================================
# 📄 File: .\nazokakeapp-137e5\404.html
# ==========================================
```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Page Not Found</title>

    <style media="screen">
      body { background: #ECEFF1; color: rgba(0,0,0,0.87); font-family: Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 0; }
      #message { background: white; max-width: 360px; margin: 100px auto 16px; padding: 32px 24px 16px; border-radius: 3px; }
      #message h3 { color: #888; font-weight: normal; font-size: 16px; margin: 16px 0 12px; }
      #message h2 { color: #ffa100; font-weight: bold; font-size: 16px; margin: 0 0 8px; }
      #message h1 { font-size: 22px; font-weight: 300; color: rgba(0,0,0,0.6); margin: 0 0 16px;}
      #message p { line-height: 140%; margin: 16px 0 24px; font-size: 14px; }
      #message a { display: block; text-align: center; background: #039be5; text-transform: uppercase; text-decoration: none; color: white; padding: 16px; border-radius: 4px; }
      #message, #message a { box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24); }
      #load { color: rgba(0,0,0,0.4); text-align: center; font-size: 13px; }
      @media (max-width: 600px) {
        body, #message { margin-top: 0; background: white; box-shadow: none; }
        body { border-top: 16px solid #ffa100; }
      }
    </style>
  </head>
  <body>
    <div id="message">
      <h2>404</h2>
      <h1>Page Not Found</h1>
      <p>The specified file was not found on this website. Please check the URL for mistakes and try again.</p>
      <h3>Why am I seeing this?</h3>
      <p>This page was generated by the Firebase Command-Line Interface. To modify it, edit the <code>404.html</code> file in your project's configured <code>public</code> directory.</p>
    </div>
  </body>
</html>

```


# ==========================================
# 📄 File: .\nazokakeapp-137e5\index.html
# ==========================================
```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Welcome to Firebase Hosting</title>

    <!-- update the version number as needed -->
    <script defer src="/__/firebase/12.13.0/firebase-app-compat.js"></script>
    <!-- include only the Firebase features as you need -->
    <script defer src="/__/firebase/12.13.0/firebase-auth-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-database-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-firestore-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-functions-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-messaging-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-storage-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-analytics-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-remote-config-compat.js"></script>
    <script defer src="/__/firebase/12.13.0/firebase-performance-compat.js"></script>
    <!-- 
      initialize the SDK after all desired features are loaded, set useEmulator to false
      to avoid connecting the SDK to running emulators.
    -->
    <script defer src="/__/firebase/init.js?useEmulator=true"></script>

    <style media="screen">
      body { background: #ECEFF1; color: rgba(0,0,0,0.87); font-family: Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 0; }
      #message { background: white; max-width: 360px; margin: 100px auto 16px; padding: 32px 24px; border-radius: 3px; }
      #message h2 { color: #ffa100; font-weight: bold; font-size: 16px; margin: 0 0 8px; }
      #message h1 { font-size: 22px; font-weight: 300; color: rgba(0,0,0,0.6); margin: 0 0 16px;}
      #message p { line-height: 140%; margin: 16px 0 24px; font-size: 14px; }
      #message a { display: block; text-align: center; background: #039be5; text-transform: uppercase; text-decoration: none; color: white; padding: 16px; border-radius: 4px; }
      #message, #message a { box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24); }
      #load { color: rgba(0,0,0,0.4); text-align: center; font-size: 13px; }
      @media (max-width: 600px) {
        body, #message { margin-top: 0; background: white; box-shadow: none; }
        body { border-top: 16px solid #ffa100; }
      }
    </style>
  </head>
  <body>
    <div id="message">
      <h2>Welcome</h2>
      <h1>Firebase Hosting Setup Complete</h1>
      <p>You're seeing this because you've successfully setup Firebase Hosting. Now it's time to go build something extraordinary!</p>
      <a target="_blank" href="https://firebase.google.com/docs/hosting/">Open Hosting Documentation</a>
    </div>
    <p id="load">Firebase SDK Loading&hellip;</p>

    <script>
      document.addEventListener('DOMContentLoaded', function() {
        const loadEl = document.querySelector('#load');
        // // 🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥
        // // The Firebase SDK is initialized and available here!
        //
        // firebase.auth().onAuthStateChanged(user => { });
        // firebase.database().ref('/path/to/ref').on('value', snapshot => { });
        // firebase.firestore().doc('/foo/bar').get().then(() => { });
        // firebase.functions().httpsCallable('yourFunction')().then(() => { });
        // firebase.messaging().requestPermission().then(() => { });
        // firebase.storage().ref('/path/to/ref').getDownloadURL().then(() => { });
        // firebase.analytics(); // call to activate
        // firebase.analytics().logEvent('tutorial_completed');
        // firebase.performance(); // call to activate
        //
        // // 🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

        try {
          let app = firebase.app();
          let features = [
            'auth', 
            'database', 
            'firestore',
            'functions',
            'messaging', 
            'storage', 
            'analytics', 
            'remoteConfig',
            'performance',
          ].filter(feature => typeof app[feature] === 'function');
          loadEl.textContent = `Firebase SDK loaded with ${features.join(', ')}`;
        } catch (e) {
          console.error(e);
          loadEl.textContent = 'Error loading the Firebase SDK, check the console.';
        }
      });
    </script>
  </body>
</html>

```


# ==========================================
# 📄 File: .\scripts\assess_baseline.py
# ==========================================
```py
import os
from collections import Counter
import firebase_admin
from firebase_admin import credentials, firestore

def scan_codebase():
    target_exts = {'.py', '.js', '.html'}
    exclude_dirs = {'.venv', '.venv_ai', '__pycache__', '.git', 'node_modules', '.agents', '.vscode'}
    
    file_count = 0
    total_lines = 0
    
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if any(file.endswith(ext) for ext in target_exts):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        total_lines += len(lines)
                        file_count += 1
                except Exception:
                    pass
    return file_count, total_lines

def check_firestore_status():
    if not firebase_admin._apps:
        # デフォルト認証（ADC）への安全なフォールバック
        firebase_admin.initialize_app()
    
    db = firestore.client()
    try:
        docs = db.collection("nazokake_items").select(["status"]).stream()
        status_counter = Counter()
        for doc in docs:
            data = doc.to_dict()
            status = data.get("status", "Missing")
            # 型チェック（文字列型として混入しているゾンビデータを炙り出す）
            status_type = type(status).__name__
            status_counter[f"{status} (Type: {status_type})"] += 1
            
        return status_counter
    except Exception as e:
        return f"Firestore Error: {e}"

if __name__ == "__main__":
    print("🔍 [Phase 1] コードベースのAST解析前ベースラインを計測中...")
    files, lines = scan_codebase()
    print(f"   => 対象ファイル数: {files} / 総行数: {lines} 行")
    
    print("\n📊 [Phase 2] Firestoreデータのクレンジング前ベースラインを監査中...")
    status_counts = check_firestore_status()
    if isinstance(status_counts, Counter):
        for stat, count in status_counts.items():
            print(f"   => Status: {stat} : {count} 件")
    else:
        print(status_counts)
    print("\n✅ 計測完了。")

```


# ==========================================
# 📄 File: .\scripts\audit_batch.py
# ==========================================
```py
# scripts/audit_batch.py
import os
import logging
from collections import Counter
from google.cloud import firestore

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 必須となる11軸のスコアキー
REQUIRED_SCORE_KEYS = {
    "S_sur", "S_nat", "S_tech", "S_emo", "S_rhy", 
    "S_sensory", "S_visual", "S_ontology", "S_cultural", 
    "S_cm", "S_prosody"
}

def audit_firestore_data():
    """
    Firestore上のなぞかけバッチ処理結果を監査し、標準出力にレポートする。
    """
    logger.info("Firestoreからのデータ取得および監査を開始します...")
    
    try:
        db = firestore.Client()
        # .stream()を使用し、ジェネレータとして順次取得（メモリ枯渇対策）
        docs = db.collection('nazokake_items').stream()
    except Exception as e:
        logger.error(f"Firestoreへの接続に失敗しました: {e}")
        return

    total_count = 0
    status_counts = Counter()
    missing_scores_count = 0
    error_reasons = Counter()

    for doc in docs:
        total_count += 1
        data = doc.to_dict()
        
        status = data.get('status', 0)
        status_counts[status] += 1

        if status == 2:
            # status: 2 (完了) の場合、11軸スコアの完全性をチェック
            scores = data.get('scores', {})
            if not REQUIRED_SCORE_KEYS.issubset(scores.keys()):
                missing_scores_count += 1
                logger.warning(f"ドキュメント {doc.id}: スコアキーに欠損があります。")
                
        elif status == 9:
            # status: 9 (エラー) の場合、エラーメッセージの傾向を集計
            error_msg = data.get('error_message', 'No error message provided')
            short_error = error_msg[:60].strip() # ログ集計用に先頭60文字で丸める
            error_reasons[short_error] += 1

    # レポート出力
    print("\n" + "="*50)
    print("📊 バッチ処理監査レポート")
    print("="*50)
    print(f"総スキャン件数: {total_count} 件")
    print(f"[0] 未処理: {status_counts.get(0, 0)} 件")
    print(f"[1] 処理中: {status_counts.get(1, 0)} 件")
    print(f"[2] 完了　: {status_counts.get(2, 0)} 件")
    print(f"[9] エラー: {status_counts.get(9, 0)} 件")
    print("-" * 50)
    
    if missing_scores_count > 0:
        print(f"⚠️ スコア欠損ドキュメント数: {missing_scores_count} 件")
    else:
        print("✅ スコア欠損: 0 件 (すべての完了データが正常です)")

    if error_reasons:
        print("\n🔥 エラー原因（status: 9）の内訳:")
        for reason, count in error_reasons.items():
            print(f"  - {count}件: {reason}...")
    print("="*50)

if __name__ == "__main__":
    audit_firestore_data()
```


# ==========================================
# 📄 File: .\scripts\audit_training_data.py
# ==========================================
```py
from google.cloud import firestore

db = firestore.Client()

def audit_training_data():
    print("📊 [Data Audit] Firestoreの学習用データの在庫を確認中...\n")
    try:
        # プロジェクトの歴史上使われてきた2つのコレクションを両方チェック
        collections = ["nazokake_items", "nazokake_evaluations"]
        
        for col_name in collections:
            # status が 2 (評価完了) のドキュメントを取得
            query = db.collection(col_name).where("status", "==", 2)
            docs = list(query.stream())
            count_total = len(docs)
            
            if count_total == 0:
                continue
                
            print(f"📁 コレクション: {col_name}")
            print(f"  ✅ 評価完了データ (status=2) 総数: {count_total} 件")
            
            # RLHF (人間の評価) が付与されているかチェック
            human_evals = sum(1 for d in docs if d.to_dict().get("FINAL_SCORE_HUMAN") is not None)
            print(f"  👨‍⚖️ うち、人間の評価(RLHF)あり: {human_evals} 件\n")
            
    except Exception as e:
        print(f"🚨 データベーススキャン中にエラーが発生しました: {e}")

if __name__ == "__main__":
    audit_training_data()

```


# ==========================================
# 📄 File: .\scripts\auto_summarize.py
# ==========================================
```py
import os
import urllib.request
import json
import sys

OLLAMA_URL = "http://localhost:11434/api/generate"
SUMMARY_FILE = "architecture_summary.md"

def get_ollama_model():
    """Ollama APIから利用可能なモデル（Gemma等）を自動探索する"""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3.0) as res:
            data = json.loads(res.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            gemma = next((m for m in models if "gemma" in m.lower()), None)
            return gemma or (models[0] if models else None)
    except Exception:
        return None

def main():
    print("🤖 ローカルLLM(Ollama)のAPIを探査しています...")
    model = get_ollama_model()
    
    if not model:
        print("❌ [Fail-Fast] OllamaのAPI(localhost:11434)に接続できませんでした。")
        print("💡 Ollamaアプリが起動しているか確認してください。")
        sys.exit(1)

    print(f"✅ モデル '{model}' を発見しました。プロジェクトの解析を開始します...")

    # 解析対象の拡張子と、無視するディレクトリ（ノイズ排除）
    target_exts = {".py", ".dart"}
    exclude_dirs = {".venv", ".venv_ai", ".venv_stable", "node_modules", ".git", "__pycache__", "build", "android", "ios", "web", "macos", "windows", "linux"}
    
    structure = []
    code_snippets = []
    
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        rel_dir = os.path.relpath(root, ".")
        if rel_dir != ".":
            structure.append(f"📁 {rel_dir}")
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in target_exts:
                filepath = os.path.join(root, file)
                structure.append(f"  📄 {file}")
                
                # トークン溢れを防ぐため各ファイルの先頭50行を抽出
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.readlines()[:50]
                        code_snippets.append(f"\n--- {filepath} ---\n" + "".join(lines))
                except Exception:
                    pass

    prompt = f"""あなたは優秀なシニアアーキテクトです。
以下の「プロジェクトのフォルダ構成」と「各ファイルの内容」を解析し、アーキテクチャの要約を作成してください。

【出力フォーマット】
以下のマークダウン形式のみを出力してください。挨拶や余計な解説は不要です。

## 1. 全体構造と主要な機能 (Screens/UI & Backend)
（各フォルダの役割と、主要な機能の概要を箇条書きでまとめる）

## 2. 状態管理とデータフロー (State Management)
（データがどこから入力され、どのファイルを通って、どのように処理・保存されるか。APIの流れや状態遷移をまとめる）

---
【フォルダ構成】
{chr(10).join(structure)}

【主要コード（先頭部分）】
{"".join(code_snippets)}
"""

    print("⏳ Ollamaにプロンプトを送信し、推論を実行中です...（数分かかる場合があります。コーヒーブレイクを推奨します☕）")

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})

    try:
        # LLM推論の待機（最大10分）
        with urllib.request.urlopen(req, timeout=600) as res:
            result = json.loads(res.read().decode("utf-8"))
            generated_text = result.get("response", "").strip()
    except Exception as e:
        print(f"❌ LLMの生成中に通信エラーが発生しました: {e}")
        sys.exit(1)

    print(f"✅ 推論完了！ {SUMMARY_FILE} に自動追記します...")
    
    # ファイルの末尾に追記
    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write("\n\n" + generated_text + "\n")

    print("🎉 [Success] 全自動要約＆追記が完了しました！")

if __name__ == "__main__":
    main()

```


# ==========================================
# 📄 File: .\scripts\bust_cache.py
# ==========================================
```py
import os
import re
import time
import subprocess

def bust_cache_and_deploy():
    print("\n================ [ 最終突破: キャッシュ・バスターと自動デプロイ ] ================")
    file_path = "frontend/index.html"
    
    if not os.path.exists(file_path):
        print(f"🚨 {file_path} が見つかりません。")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 今の時間のタイムスタンプを生成 (例: 1716974000)
    new_timestamp = str(int(time.time()))
    
    # 正規表現で古いタイムスタンプ (app_final.js?v=〇〇) を見つけて、新しいものに書き換える
    new_content = re.sub(r'app_final\.js\?v=\d+', f'app_final.js?v={new_timestamp}', content)
    
    if content == new_content:
        print("⚠️ app_final.js?v=〇〇 の記述が見つかりませんでした。")
        return

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print(f"✅ index.html のタイムスタンプを最新 ({new_timestamp}) に更新しました！")
    print("🚀 続けて、Firebaseへ自動デプロイを実行します...")
    
    try:
        # Pythonから直接デプロイコマンドを叩く
        subprocess.run(["firebase", "deploy", "--only", "hosting"], check=True, shell=True)
        print("\n🎉 デプロイ完了！ ブラウザへの強制ダウンロード命令を発動しました。")
    except subprocess.CalledProcessError as e:
        print(f"\n🚨 デプロイ中にエラーが発生しました: {e}")

if __name__ == "__main__":
    bust_cache_and_deploy()

```


# ==========================================
# 📄 File: .\scripts\check_latest_status.py
# ==========================================
```py
import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

def check_status():
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    # 安全な初期化（以前成功したロジック）
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 直近に作成された5件のなぞかけの状態（ステータス）を確認します...")
    try:
        # 作成日時の降順で最新5件を取得
        docs = db.collection("nazokake_items").order_by("created_at", direction=firestore.Query.DESCENDING).limit(5).stream()
        
        found = False
        for doc in docs:
            found = True
            data = doc.to_dict()
            title = data.get("A_TITLE", "不明")
            status = data.get("status", "不明")
            author = data.get("author", "不明")
            has_scores = "あり" if len(data.get("scores", {})) > 0 else "なし"
            print(f"📌 お題: {title:<10} | 著者: {author:<25} | Status: {status} | AI評価: {has_scores}")
            
        if not found:
            print("⚠️ データが見つかりませんでした。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    check_status()

```
