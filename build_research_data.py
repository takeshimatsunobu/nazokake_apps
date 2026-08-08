import csv
import json
import html
import re
from pathlib import Path

# --- 定義 ---
REPO_ROOT = Path(__file__).parent
OUTPUT_JSON = REPO_ROOT / "apps" / "evaluator" / "frontend" / "public" / "data" / "research_data.json"

TARGET_IDS = [
    "basic-form", "academic-definition", "dictionary-comparison", 
    "evolution-academic", "evolution-comic", "research_physiology", 
    "research_others", "culture_japan", "culture_world_academic", "culture_world_survey"
]

def read_csv_safe(file_name):
    path = REPO_ROOT / file_name
    if not path.exists():
        return []
    for enc in ['utf-8-sig', 'cp932', 'euc-jp']:
        try:
            with open(path, 'r', encoding=enc) as f:
                reader = csv.reader(f)
                next(reader) # ヘッダースキップ
                return list(reader)
        except Exception:
            continue
    return []


def read_csv_skip(file_name, skip_lines=1):
    path = REPO_ROOT / file_name
    if not path.exists():
        return []
    for enc in ['utf-8-sig', 'cp932', 'utf-8', 'euc-jp']:
        try:
            with open(path, 'r', encoding=enc) as f:
                reader = csv.reader(f)
                for _ in range(skip_lines):
                    next(reader)
                return list(reader)
        except Exception:
            continue
    return []

def build_research_physiology():
    # 021は二重ヘッダなので2行スキップ
    rows = read_csv_skip("021 なぞかけの生理学的な研究(JSON).csv", skip_lines=2)
    if not rows:
        return "<div class='p-4 text-slate-500'>データがありません。</div>"

    # cat -> chap -> [article_html, ...] の順序を保ったまま2階層にグループ化
    grouped = {}
    for row in rows:
        if len(row) < 9:
            continue
        item_id, cat, chap, title, exp, rel, b_title, b_year, b_res = [r.strip() for r in row]
        if not title:
            continue

        item = {
            "id": item_id, "title": title, "exp": exp, "rel": rel,
            "b_title": b_title, "b_year": b_year, "b_res": b_res,
        }
        article = f'''
        <details class="group/item bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <summary class="cursor-pointer p-4 flex justify-between items-center hover:bg-slate-50 transition">
                <h4 class="text-[15px] md:text-base font-bold text-emerald-800 flex items-center gap-2 m-0">
                    <span class="text-xs font-mono text-emerald-700 bg-emerald-100 px-2 py-1 rounded">{html.escape(item["id"])}</span>
                    🧠 {html.escape(item["title"])}
                </h4>
                <span class="text-emerald-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 pt-0 border-t border-slate-100 bg-white">
                <div class="mb-4 mt-3"><h5 class="text-xs font-bold text-slate-400 mb-1">実験・結果</h5><p class="text-sm text-slate-700 leading-relaxed">{html.escape(item["exp"])}</p></div>
                <div class="mb-4"><h5 class="text-xs font-bold text-slate-400 mb-1">なぞかけとの関係</h5><p class="text-sm text-slate-700 leading-relaxed">{html.escape(item["rel"])}</p></div>
                <div class="bg-slate-100 p-3 rounded-lg text-xs text-slate-500 border border-slate-200">
                    📚 <strong>{html.escape(item["b_title"])}</strong> ({html.escape(item["b_year"])})<br>👤 {html.escape(item["b_res"])}
                </div>
            </div>
        </details>
        '''
        grouped.setdefault(cat, {}).setdefault(chap, []).append(article)

    html_parts = ["<div class='space-y-6'>"]
    for cat, chapters in grouped.items():
        html_parts.append(f'''
        <details class="group bg-white rounded-xl border border-emerald-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-emerald-50 font-bold text-emerald-900 flex justify-between items-center hover:bg-emerald-100 transition">{html.escape(cat)} <span class="group-open:rotate-180 transition-transform">▼</span></summary>
            <div class="p-4 space-y-4">
        ''')
        for chap, articles in chapters.items():
            html_parts.append(f'''
            <details class="group/chap bg-slate-50 rounded-lg border border-slate-200 overflow-hidden">
                <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">{html.escape(chap)} <span class="group-open/chap:rotate-180 transition-transform">▼</span></summary>
                <div class="p-4 grid grid-cols-1 gap-4">
            ''')
            html_parts.extend(articles)
            html_parts.append("</div></details>")
        html_parts.append("</div></details>")
    html_parts.append("</div>")
    return "".join(html_parts)

def build_culture_japan():
    rows = read_csv_skip("031 日本の言葉遊び文化（完成）.csv", skip_lines=1)
    if not rows:
        return "<div class='p-4 text-slate-500'>データがありません。</div>"

    # 1. name(文化名)でグループ化。era/descはグループの代表値として最初の行を採用
    grouped = {}
    for row in rows:
        if len(row) < 11:
            continue
        name, era, desc, actors, bg, atk, def_reply, point, terms, ref, _ = [r.strip() for r in row]
        if not name:
            continue

        if name not in grouped:
            grouped[name] = {'era': era, 'desc': desc, 'episodes': []}
        grouped[name]['episodes'].append({
            'actors': actors, 'bg': bg, 'atk': atk, 'def_reply': def_reply,
            'point': point, 'terms': terms, 'ref': ref,
        })

    # 2. Tailwind HTMLの生成（2階層アコーディオン: 文化名 -> 当事者エピソード）
    html_parts = ["<div class='space-y-6'>"]
    for name, data in grouped.items():
        era, desc = data['era'], data['desc']
        html_parts.append(f'''
        <details class="group bg-white rounded-xl border border-rose-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-rose-50 font-bold text-rose-900 flex justify-between items-center hover:bg-rose-100 transition">
                <span class="flex items-center gap-2"><span class="text-xl">🎌</span> {html.escape(name)} <span class="text-sm font-normal text-slate-500">({html.escape(era)})</span></span>
                <span class="text-rose-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-rose-50/30">
                <p class="text-sm text-slate-700 leading-relaxed mb-2">{html.escape(desc)}</p>
                <div class="space-y-4">
        ''')
        for ep in data['episodes']:
            html_parts.append(f'''
                <details class="group/item bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden">
                    <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                        <span class="flex items-center gap-2"><span class="text-lg">🎭</span> {html.escape(ep['actors'])}</span>
                        <span class="text-slate-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
                    </summary>
                    <div class="p-4 pt-0 border-t border-slate-100 bg-white">
                        <div class="mb-4 mt-3">
                            <h5 class="text-xs font-bold text-slate-400 mb-1">背景</h5>
                            <p class="text-sm text-slate-700 leading-relaxed">{html.escape(ep['bg'])}</p>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <div class="bg-rose-50 p-3 rounded border border-rose-100">
                                <h5 class="text-xs font-bold text-rose-700 mb-1">🗡️ 攻撃 (状況)</h5>
                                <p class="text-sm text-slate-800">{html.escape(ep['atk'])}</p>
                            </div>
                            <div class="bg-blue-50 p-3 rounded border border-blue-100">
                                <h5 class="text-xs font-bold text-blue-700 mb-1">🛡️ 切り返し</h5>
                                <p class="text-sm text-slate-800">{html.escape(ep['def_reply'])}</p>
                            </div>
                        </div>
                        <div class="bg-amber-50 p-3 rounded text-sm text-slate-800 border border-amber-200 mb-4">
                            <span class="font-bold text-amber-700">評価ポイント:</span> {html.escape(ep['point'])}
                        </div>
                        <div class="bg-slate-100 p-3 rounded-lg text-xs text-slate-500 border border-slate-200">
                            <span class="font-bold">用語解説:</span> {html.escape(ep['terms'])}<br>
                            <span class="font-bold">引用元:</span> {html.escape(ep['ref'])}
                        </div>
                    </div>
                </details>
            ''')
        html_parts.append("</div></div></details>")
    html_parts.append("</div>")
    return "".join(html_parts)

def _unwrap_details(block):
    # フロント側でも <details> によるアコーディオンを描画するため、
    # 抽出ブロックに残った <details>/<summary> を取り除き二重ネストを防ぐ
    block = re.sub(r'<summary>.*?</summary>', '', block, flags=re.DOTALL)
    block = re.sub(r'<details[^>]*>', '', block)
    block = re.sub(r'</details>', '', block)
    return block.strip()

def extract_html_block(filename, target_id):
    path = REPO_ROOT / "apps" / "evaluator" / "frontend" / "public" / "research_data" / filename
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # <details ...> ... </details> を大雑把に抽出し、中身に target_id の文字列（日本語タイトルなど）が含まれるものを探す
        # 今回は簡易的に、抽出先のマッピングを決め打ちします
        blocks = re.findall(r'(<details.*?</details>)', content, re.DOTALL)

        if target_id == "basic-form" and len(blocks) > 0:
            return _unwrap_details(blocks[0])
        if target_id == "academic-definition" and len(blocks) > 1:
            return _unwrap_details(blocks[1])
        if target_id == "dictionary-comparison" and len(blocks) > 2:
            return _unwrap_details(blocks[2])

        if target_id == "evolution-academic" and len(blocks) > 0:
            return _unwrap_details(blocks[0])
        if target_id == "evolution-comic" and len(blocks) > 1:
            return _unwrap_details(blocks[1])
    except Exception:
        pass
    return None

QUADRANTS = ["第1象限", "第2象限", "第3象限", "第4象限"]

def _quadrant_key(quad_value):
    return next((q for q in QUADRANTS if quad_value.startswith(q)), None)

def build_culture_world_academic():
    rows = read_csv_skip("041世界の言語活動調査.(学術的).csv", skip_lines=1)
    if not rows:
        return "<div class='p-4 text-slate-500'>データがありません。</div>"

    grouped = {q: [] for q in QUADRANTS}
    for row in rows:
        if len(row) < 17:
            continue
        quad, country, name, definition, structure, context, function, effect = row[:8]
        examples = [row[8:11], row[11:14], row[14:17]]
        key = _quadrant_key(quad)
        if key is None or not name:
            continue
        grouped[key].append({
            'quad_label': quad, 'country': country, 'name': name,
            'definition': definition, 'structure': structure,
            'context': context, 'function': function, 'effect': effect,
            'examples': examples,
        })

    html_parts = ["<div class='space-y-12'>"]
    for q in QUADRANTS:
        items = grouped[q]
        if not items:
            continue
        label = items[0]['quad_label']
        html_parts.append(f"<section class='category-block'><h2 class='text-2xl font-extrabold text-slate-800 border-b-4 border-indigo-600 pb-3 mb-6'>🌐 {html.escape(label)}</h2>")
        html_parts.append("<div class='grid grid-cols-1 md:grid-cols-2 gap-6'>")
        for item in items:
            ex_html = "".join(
                f'''<div class='bg-slate-50 p-3 rounded-lg mb-2 text-xs border border-slate-100'>
                    <div class='font-bold text-slate-500 mb-1'>{html.escape(ex[0])}</div>
                    <div class='text-slate-800 mb-1'>{html.escape(ex[1])}</div>
                    <div class='text-slate-600'>{html.escape(ex[2])}</div>
                </div>'''
                for ex in item['examples'] if any(c.strip() for c in ex)
            )
            html_parts.append(f'''
            <article class='bg-white rounded-xl p-5 shadow-sm border border-indigo-100'>
                <h4 class='text-base font-bold text-indigo-800 mb-2'>{html.escape(item['country'])}｜{html.escape(item['name'])}</h4>
                <p class='text-sm text-slate-700 mb-3'>{html.escape(item['definition'])}</p>
                <div class='grid grid-cols-1 gap-1.5 text-xs mb-3 bg-indigo-50/50 p-3 rounded-lg'>
                    <div><span class='font-bold text-indigo-700'>言語構造：</span>{html.escape(item['structure'])}</div>
                    <div><span class='font-bold text-indigo-700'>社会背景：</span>{html.escape(item['context'])}</div>
                    <div><span class='font-bold text-indigo-700'>社会的機能：</span>{html.escape(item['function'])}</div>
                    <div><span class='font-bold text-indigo-700'>心理的効果：</span>{html.escape(item['effect'])}</div>
                </div>
                {ex_html}
            </article>
            ''')
        html_parts.append("</div></section>")
    html_parts.append("</div>")
    return "".join(html_parts)

def build_culture_world_survey():
    rows = read_csv_skip("042 世界の言語活動調査(実態調査).csv", skip_lines=1)
    if not rows:
        return "<div class='p-4 text-slate-500'>データがありません。</div>"

    TYPE_STYLE = {
        '【事実】': 'bg-emerald-100 text-emerald-700',
        '【都市伝説】': 'bg-amber-100 text-amber-700',
    }
    grouped = {q: [] for q in QUADRANTS}
    for row in rows:
        if len(row) < 17:
            continue
        quad, country, typ, name, practice, function, effect, fact_check = row[:8]
        examples = [row[8:11], row[11:14], row[14:17]]
        key = _quadrant_key(quad)
        if key is None or not name:
            continue
        grouped[key].append({
            'quad_label': quad, 'country': country, 'type': typ, 'name': name,
            'practice': practice, 'function': function, 'effect': effect,
            'fact_check': fact_check, 'examples': examples,
        })

    html_parts = ["<div class='space-y-12'>"]
    for q in QUADRANTS:
        items = grouped[q]
        if not items:
            continue
        label = items[0]['quad_label']
        html_parts.append(f"<section class='category-block'><h2 class='text-2xl font-extrabold text-slate-800 border-b-4 border-rose-600 pb-3 mb-6'>🗺️ {html.escape(label)}</h2>")
        html_parts.append("<div class='grid grid-cols-1 md:grid-cols-2 gap-6'>")
        for item in items:
            badge_cls = TYPE_STYLE.get(item['type'], 'bg-slate-100 text-slate-600')
            ex_html = "".join(
                f'''<div class='bg-slate-50 p-3 rounded-lg mb-2 text-xs border border-slate-100'>
                    <div class='font-bold text-slate-500 mb-1'>{html.escape(ex[0])}</div>
                    <div class='text-slate-800 mb-1'>{html.escape(ex[1])}</div>
                    <div class='text-slate-600'>{html.escape(ex[2])}</div>
                </div>'''
                for ex in item['examples'] if any(c.strip() for c in ex)
            )
            html_parts.append(f'''
            <article class='bg-white rounded-xl p-5 shadow-sm border border-rose-100'>
                <h4 class='text-base font-bold text-rose-800 mb-2 flex items-center gap-2 flex-wrap'>
                    <span>{html.escape(item['country'])}｜{html.escape(item['name'])}</span>
                    <span class='text-xs font-bold px-2 py-0.5 rounded {badge_cls}'>{html.escape(item['type'])}</span>
                </h4>
                <p class='text-sm text-slate-700 mb-3'>{html.escape(item['practice'])}</p>
                <div class='grid grid-cols-1 gap-1.5 text-xs mb-3 bg-rose-50/50 p-3 rounded-lg'>
                    <div><span class='font-bold text-rose-700'>社会的機能：</span>{html.escape(item['function'])}</div>
                    <div><span class='font-bold text-rose-700'>心理的効果：</span>{html.escape(item['effect'])}</div>
                    <div><span class='font-bold text-rose-700'>事実確認：</span>{html.escape(item['fact_check'])}</div>
                </div>
                {ex_html}
            </article>
            ''')
        html_parts.append("</div></section>")
    html_parts.append("</div>")
    return "".join(html_parts)

def build_research_others():
    rows = read_csv_safe("022 なぞかけその他の研究の現状.csv")
    if not rows:
        return "<div class='p-4 text-red-500 font-bold'>データソースが見つかりません。</div>"
    
    # 1. データの階層化 (Category -> Chapter -> Items)
    grouped = {}
    for row in rows:
        if len(row) < 10:
            continue
        cat, cat_desc, chap, item_id, title, analysis, relation, b_title, b_year, b_res = [r.strip() for r in row]
        if not cat:
            continue
        
        if cat not in grouped:
            grouped[cat] = {'desc': cat_desc, 'chapters': {}}
        if chap not in grouped[cat]['chapters']:
            grouped[cat]['chapters'][chap] = []
        
        grouped[cat]['chapters'][chap].append({
            'id': item_id, 'title': title, 'analysis': analysis, 'relation': relation,
            'b_title': b_title, 'b_year': b_year, 'b_res': b_res
        })
        
    # 2. Tailwind HTMLの生成（3階層アコーディオン: Category -> Chapter -> Item）
    html_parts = ["<div class='research-others-container space-y-6'>"]
    for cat, cat_data in grouped.items():
        html_parts.append(f'''
        <details class="group bg-white rounded-xl border border-emerald-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-emerald-50 font-bold text-emerald-900 flex justify-between items-center hover:bg-emerald-100 transition">
                <span class="flex items-center gap-2"><span class="text-xl">🏛️</span> {html.escape(cat)}</span>
                <span class="text-emerald-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-emerald-50/30">
        ''')
        if cat_data['desc']:
            html_parts.append(f"<p class=\"text-sm text-emerald-800/80 mb-4 px-2\">{html.escape(cat_data['desc']).replace(chr(10), '<br>')}</p>")

        for chap, items in cat_data['chapters'].items():
            html_parts.append(f'''
            <details class="group/chap bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                    <span class="flex items-center gap-2"><span class="text-lg">📖</span> {html.escape(chap)}</span>
                    <span class="text-slate-400 group-open/chap:rotate-180 transition-transform duration-300">▼</span>
                </summary>
                <div class="p-4 grid grid-cols-1 gap-4 bg-slate-50">
            ''')

            for item in items:
                html_parts.append(f"""
                <details class="group/item bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                    <summary class="cursor-pointer p-4 flex justify-between items-center hover:bg-slate-50 transition">
                        <h4 class="text-[15px] md:text-base font-bold text-emerald-800 flex items-center gap-2 m-0">
                            <span class="text-xs font-mono text-emerald-700 bg-emerald-100 px-2 py-1 rounded">{html.escape(item['id'])}</span>
                            🔬 {html.escape(item['title'])}
                        </h4>
                        <span class="text-emerald-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
                    </summary>
                    <div class="p-4 pt-0 border-t border-slate-100 bg-white">
                        <div class="mb-4 mt-3"><h5 class="text-xs font-bold text-slate-400 mb-1">分析・実験</h5><p class="text-sm text-slate-700 leading-relaxed">{html.escape(item['analysis']).replace(chr(10), '<br>')}</p></div>
                        <div class="mb-4 p-3 bg-amber-50/70 rounded border border-amber-100"><h5 class="text-xs font-bold text-amber-700 mb-1">なぞかけとの関係</h5><p class="text-sm text-slate-800 leading-relaxed">{html.escape(item['relation']).replace(chr(10), '<br>')}</p></div>
                        <div class="bg-slate-100 p-3 rounded-lg text-xs text-slate-500 border border-slate-200">
                            📚 <strong>{html.escape(item['b_title'])}</strong> ({html.escape(item['b_year'])})<br>👤 {html.escape(item['b_res'])}
                        </div>
                    </div>
                </details>
                """)
            html_parts.append("</div></details>")
        html_parts.append("</div></details>")
    html_parts.append("</div>")
    return "".join(html_parts)


def _parse_embedded_culture_json(row):
    # CSVセルへの誤貼り付けで混入した生JSON（{"status":...,"cultures":[...]}）を検出し、
    # 通常行と同じ形（quad/name/definition/func/cases）にマッピングする。該当しなければNone。
    joined = "".join(row)
    if '{"status":' not in joined and '{"cultures":' not in joined:
        return None

    json_str = next((cell.strip() for cell in row if cell.strip().startswith('{')), None)
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    cultures = data.get('cultures') or []
    if not cultures:
        return None

    quad_fallback = row[0].strip() if row and row[0].strip() else "第4象限"
    items = []
    for culture in cultures:
        cases = []
        for ex in culture.get('historical_examples', []) or []:
            ctx = ex.get('background', '') or ''
            attack = ex.get('attack', '') or ''
            humor = ex.get('humor_return', '') or ''
            expr = f"{attack} ➡️ {humor}" if (attack or humor) else ''
            ana = ex.get('evaluation', '') or ''
            cases.append((ctx, expr, ana))
        items.append({
            'quad': quad_fallback,
            'name': culture.get('culture_name', ''),
            'definition': culture.get('historical_background', ''),
            'func': culture.get('social_function', ''),
            'cases': cases,
        })
    return items


def build_culture_world_academic_v3():
    rows = read_csv_skip("041世界の言語活動調査.(学術的).csv", skip_lines=1)
    if not rows: return "<div class='p-4 text-slate-500'>データがありません。</div>"
    
    # 全体説明（A）のHTML
    intro_html = '''
    <div class="bg-white text-slate-800 p-6 md:p-8 rounded-2xl shadow-sm mb-12 border border-emerald-200">
        <h2 class="text-2xl md:text-3xl font-extrabold text-emerald-800 mb-8 border-b-2 border-emerald-200 pb-4">
            🌍 世界の言語文化：コミュニケーションの4象限モデル
        </h2>

        <!-- 1. 軸の解説 -->
        <section class="mb-10">
            <h3 class="text-xl font-bold text-emerald-700 mb-4 flex items-center gap-2"><span class="text-2xl">🧭</span> 1. 分類の「理屈」：コミュニケーションを分ける2つの軸</h3>
            <p class="text-slate-600 leading-relaxed mb-6 text-sm md:text-base">人間の言葉は無数にあるように見えて、実は「相手との関係をどうしたいか（目的）」と「言葉をどう使うか（手段）」の2つの軸でMECE（漏れなくダブりなく）に4つの象限に整理できます。</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="bg-emerald-50 p-5 rounded-xl border border-emerald-100">
                    <h4 class="font-bold text-blue-700 mb-3 text-lg border-b border-blue-200 pb-2">↕️ 縦軸（関係性のベクトル）</h4>
                    <ul class="space-y-3 text-sm text-slate-700">
                        <li class="flex gap-2"><span class="font-bold text-blue-600 w-16 shrink-0">【協調】</span> <span>相手と結びつきたい、社会の平穏を維持したい、仲間になりたい。</span></li>
                        <li class="flex gap-2"><span class="font-bold text-rose-600 w-16 shrink-0">【対立】</span> <span>相手とぶつかりたい、不満を伝えたい、自分の正しさを証明したい。</span></li>
                    </ul>
                </div>
                <div class="bg-emerald-50 p-5 rounded-xl border border-emerald-100">
                    <h4 class="font-bold text-amber-700 mb-3 text-lg border-b border-amber-200 pb-2">↔️ 横軸（表現のモード）</h4>
                    <ul class="space-y-3 text-sm text-slate-700">
                        <li class="flex gap-2"><span class="font-bold text-amber-600 w-20 shrink-0">【直接的】</span> <span>効率重視。事実や論理をストレートに伝える（コスパ・正論）。</span></li>
                        <li class="flex gap-2"><span class="font-bold text-purple-600 w-20 shrink-0">【間接的】</span> <span>遊び重視。比喩、隠語、ユーモア、ルール（制約）のフィルターを通す。</span></li>
                    </ul>
                </div>
            </div>
        </section>

        <!-- 2. 象限ごとの意味 -->
        <section class="mb-10">
            <h3 class="text-xl font-bold text-emerald-700 mb-4 flex items-center gap-2"><span class="text-2xl">🧩</span> 2. 各象限の意味（人間社会における機能）</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                <!-- Q1 -->
                <div class="bg-white p-5 rounded-xl border border-slate-200 border-t-4 border-t-blue-500 shadow-sm hover:shadow-md transition">
                    <h4 class="font-bold text-blue-700 mb-1 text-lg">第1象限：秩序と伝達</h4>
                    <p class="text-xs text-blue-500 mb-3 font-mono">直接的 × 協調</p>
                    <p class="text-sm text-slate-800 font-bold mb-3 pb-2 border-b border-slate-100">社会の歯車を摩擦なく回すための「潤滑油」</p>
                    <p class="text-sm text-slate-600 mb-2"><span class="text-slate-400">具体例:</span> マニュアル敬語、定型文、ポリコレ、タブー</p>
                    <p class="text-sm text-slate-600 leading-relaxed mb-3"><span class="text-slate-400">機能:</span> 距離や上下関係を明確にし「波風を立てないこと」を最優先。見知らぬ人とも安全に生活できる。</p>
                    <div class="bg-blue-50 p-3 rounded text-sm text-blue-900 border border-blue-100">
                        <span class="font-bold text-rose-600">⚠️ ペイン:</span> 炎上を恐れ肥大化。本音が言えず言葉狩りに怯える「AIのような無難な言葉」が現代人に息苦しさを与える。
                    </div>
                </div>
                <!-- Q2 -->
                <div class="bg-white p-5 rounded-xl border border-slate-200 border-t-4 border-t-amber-500 shadow-sm hover:shadow-md transition">
                    <h4 class="font-bold text-amber-700 mb-1 text-lg">第2象限：共感と審美</h4>
                    <p class="text-xs text-amber-500 mb-3 font-mono">間接的 × 協調</p>
                    <p class="text-sm text-slate-800 font-bold mb-3 pb-2 border-b border-slate-100">「私たち」という居場所を作る「暗号と見立て」</p>
                    <p class="text-sm text-slate-600 mb-2"><span class="text-slate-400">具体例:</span> 若者言葉、ネットスラング、詩的な比喩、女房言葉</p>
                    <p class="text-sm text-slate-600 leading-relaxed mb-3"><span class="text-slate-400">機能:</span> あえて別の言葉に変換し、解読できた者同士の間にアハ体験と深い連帯感を生み出す。</p>
                    <div class="bg-amber-50 p-3 rounded text-sm text-amber-900 border border-amber-100">
                        <span class="font-bold text-emerald-600">💡 インサイト:</span> なぞかけの面白さの源泉（UXのコア）は、まさにこの「見立てによる脳の快感」にある。
                    </div>
                </div>
                <!-- Q3 -->
                <div class="bg-white p-5 rounded-xl border border-slate-200 border-t-4 border-t-rose-500 shadow-sm hover:shadow-md transition">
                    <h4 class="font-bold text-rose-700 mb-1 text-lg">第3象限：論争と闘争</h4>
                    <p class="text-xs text-rose-500 mb-3 font-mono">直接的 × 対立</p>
                    <p class="text-sm text-slate-800 font-bold mb-3 pb-2 border-b border-slate-100">相手を屈服させ、社会を分断する「刃（やいば）」</p>
                    <p class="text-sm text-slate-600 mb-2"><span class="text-slate-400">具体例:</span> SNSでのレスバ、キャンセルカルチャー、誹謗中傷</p>
                    <p class="text-sm text-slate-600 leading-relaxed mb-3"><span class="text-slate-400">機能:</span> 自分の正しさを証明し、論理や強い言葉で直接的に攻撃する。ディベートでの勝敗が重視される。</p>
                    <div class="bg-rose-50 p-3 rounded text-sm text-rose-900 border border-rose-100">
                        <span class="font-bold text-rose-600">⚠️ ペイン:</span> 勝敗がついても深い恨みを残す。エコーチェンバーと相まって、修復不可能な社会の分断と炎上を引き起こす。
                    </div>
                </div>
                <!-- Q4 -->
                <div class="bg-white p-5 rounded-xl border border-slate-200 border-t-4 border-t-purple-500 shadow-sm hover:shadow-md transition">
                    <h4 class="font-bold text-purple-700 mb-1 text-lg">第4象限：対立の遊戯的昇華</h4>
                    <p class="text-xs text-purple-500 mb-3 font-mono">間接的 × 対立</p>
                    <p class="text-sm text-slate-800 font-bold mb-3 pb-2 border-b border-slate-100">争いを笑いと和解に変える「魔法のクッション」</p>
                    <p class="text-sm text-slate-600 mb-2"><span class="text-slate-400">具体例:</span> なぞかけ、イヌイットの即興詩バトル、冗談関係</p>
                    <p class="text-sm text-slate-600 leading-relaxed mb-3"><span class="text-slate-400">機能:</span> 怒りや対立を「ユーモア」やルールの枠に押し込む。暴力沙汰にならず和解できる、人類究極のサバイバル技術。</p>
                </div>
            </div>
        </section>

        <!-- 3. ストーリー -->
        <section class="bg-emerald-50 p-6 rounded-xl border border-emerald-200 shadow-sm relative overflow-hidden">
            <div class="absolute top-0 right-0 p-4 opacity-10 text-6xl">💊</div>
            <h3 class="text-xl font-bold text-emerald-800 mb-4 relative z-10">🚀 全体を貫くストーリー（なぜ今、なぞかけアプリなのか）</h3>
            <p class="text-sm md:text-base text-emerald-900 leading-relaxed relative z-10">
                現代のコミュニケーションは完全に壊れかけています。SNSでは、<strong>第3象限（論破と炎上）</strong>で血を流し合うか、それを恐れて<strong>第1象限（ポリコレや定型文）</strong>という無菌室に逃げ込み、息を潜めるかの二極化に陥っています。<br><br>
                しかし、人類は本来、怒りや対立を<strong>第4象限（ユーモアと制約のゲーム）</strong>に変換して安全にガス抜きする知恵を持っていました。そして、<strong>第2象限（見立てと暗号）</strong>を解読する快感によって仲間との深い絆を作ってきたのです。<br><br>
                なぞかけアプリは、ただの暇つぶしではありません。第1象限の息苦しさと第3象限の争いを抜け出し、第2象限の快感を用いながら、<strong>第4象限の機能（本音を笑いに変える安全弁）を現代のデジタル空間に再実装する、社会的な処方箋</strong>なのです。
            </p>
        </section>
    </div>
    '''

    # マップ・国選択表示エリア（理論体系の直下に出力）
    map_and_display_html = '''
    <div class="mb-8 p-4 bg-white rounded-xl shadow-sm border border-slate-200">
        <h3 class="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">🗺️ 地図から国を選択</h3>
        <div id="world-map-container" class="w-full h-[400px] bg-sky-50 rounded-lg overflow-hidden border border-slate-200"></div>
    </div>
    <div id="country-display-area" class="min-h-[200px] p-6 bg-slate-50 border border-slate-200 rounded-xl shadow-inner text-center text-slate-500">
        🌍 地図上の国をタップすると、その国の言語文化が表示されます。
    </div>
    '''

    # 国別にグループ化
    grouped = {}
    for row in rows:
        if len(row) < 17: continue
        quad = row[0].strip()
        country = row[1].strip()
        if country not in grouped: grouped[country] = []
        grouped[country].append(row)

    # 対象国アコーディオン（地図クリックで表示するため、通常は非表示のブロックとして出力）
    country_blocks = []
    for country, items in grouped.items():
        country_parts = [f'''
        <details class="group bg-white rounded-xl border border-indigo-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-indigo-50 font-bold text-indigo-900 flex justify-between items-center hover:bg-indigo-100 transition">
                <span class="flex items-center gap-2"><span class="text-2xl">🌍</span> {html.escape(country)}</span>
                <span class="text-indigo-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-indigo-50/30">
        ''']

        # 象限＋事象名アコーディオン
        for row in items:
            parsed = _parse_embedded_culture_json(row)
            if parsed is None:
                r = [col.strip() for col in row]
                quad, _, name, definition, structure, bg, func, effect, ex1_ctx, ex1_expr, ex1_ana, ex2_ctx, ex2_expr, ex2_ana, ex3_ctx, ex3_expr, ex3_ana = r[:17]
                parsed = [{
                    'quad': quad, 'name': name, 'definition': definition, 'func': func,
                    'cases': [(ex1_ctx, ex1_expr, ex1_ana), (ex2_ctx, ex2_expr, ex2_ana), (ex3_ctx, ex3_expr, ex3_ana)],
                }]

            for entry in parsed:
                # 事例カードの生成
                cases_html = ""
                for ctx, expr, ana in entry['cases']:
                    if expr:
                        cases_html += f'''
                        <div class="bg-slate-50 p-3 rounded-lg border border-slate-200 shadow-sm">
                            <div class="text-xs font-bold text-slate-500 mb-1">状況: {html.escape(ctx)}</div>
                            <div class="text-sm text-slate-800 font-bold mb-2">表現: {html.escape(expr)}</div>
                            <div class="text-xs text-slate-600 bg-white p-2 rounded border border-slate-100">分析: {html.escape(ana)}</div>
                        </div>
                        '''

                country_parts.append(f'''
                <details class="group/item bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                    <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                        <span class="flex items-center gap-2">
                            <span class="text-xs font-mono text-indigo-700 bg-indigo-100 px-2 py-1 rounded">{html.escape(entry['quad'])}</span>
                            {html.escape(entry['name'])}
                        </span>
                        <span class="text-slate-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
                    </summary>
                    <div class="p-4 border-t border-slate-100 bg-white space-y-4">
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <h5 class="text-xs font-bold text-slate-400 mb-1">定義・言語構造</h5>
                                <p class="text-sm text-slate-700 leading-relaxed">{html.escape(entry['definition'])}</p>
                            </div>
                            <div>
                                <h5 class="text-xs font-bold text-slate-400 mb-1">社会的機能 / 心理的効果</h5>
                                <p class="text-sm text-slate-700 leading-relaxed">{html.escape(entry['func'])}</p>
                            </div>
                        </div>
                        <div>
                            <h5 class="text-xs font-bold text-indigo-800 mb-2 border-b border-indigo-100 pb-1 flex items-center gap-1">📚 事例・ケーススタディ</h5>
                            <div class="grid grid-cols-1 gap-3">
                                {cases_html}
                            </div>
                        </div>
                    </div>
                </details>
                ''')

        country_parts.append("</div></details>")
        country_blocks.append(f'<div id="country-data-{html.escape(country)}" style="display:none;">' + "".join(country_parts) + '</div>')

    html_parts = [intro_html, map_and_display_html] + country_blocks
    return "".join(html_parts)

def build_culture_world_survey_v3():
    rows = read_csv_skip("042 世界の言語活動調査(実態調査).csv", skip_lines=1)
    if not rows: return "<div class='p-4 text-slate-500'>データがありません。</div>"

    # マップ・国選択表示エリア（一番上に出力）
    map_and_display_html = '''
    <div class="mb-8 p-4 bg-white rounded-xl shadow-sm border border-slate-200">
        <h3 class="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">🗺️ 地図から国を選択</h3>
        <div id="world-map-container" class="w-full h-[400px] bg-sky-50 rounded-lg overflow-hidden border border-slate-200"></div>
    </div>
    <div id="country-display-area" class="min-h-[200px] p-6 bg-slate-50 border border-slate-200 rounded-xl shadow-inner text-center text-slate-500">
        🌍 地図上の国をタップすると、その国の言語文化が表示されます。
    </div>
    '''

    grouped = {}
    for row in rows:
        if len(row) < 17: continue
        quad = row[0].strip()
        country = row[1].strip()
        if country not in grouped: grouped[country] = []
        grouped[country].append(row)

    # 対象国アコーディオン（地図クリックで表示するため、通常は非表示のブロックとして出力）
    country_blocks = []
    for country, items in grouped.items():
        country_parts = [f'''
        <details class="group bg-white rounded-xl border border-teal-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-teal-50 font-bold text-teal-900 flex justify-between items-center hover:bg-teal-100 transition">
                <span class="flex items-center gap-2"><span class="text-2xl">🌍</span> {html.escape(country)}</span>
                <span class="text-teal-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-teal-50/30">
        ''']
        for row in items:
            parsed = _parse_embedded_culture_json(row)
            if parsed is None:
                r = [col.strip() for col in row]
                quad, _, type_label, name, content, func, effect, fact_check, ex1_ctx, ex1_expr, ex1_ana, ex2_ctx, ex2_expr, ex2_ana, ex3_ctx, ex3_expr, ex3_ana = r[:17]
                parsed = [{
                    'quad': quad, 'type_label': type_label, 'name': name,
                    'content': content, 'fact_check': fact_check,
                    'cases': [(ex1_ctx, ex1_expr, ex1_ana), (ex2_ctx, ex2_expr, ex2_ana), (ex3_ctx, ex3_expr, ex3_ana)],
                }]
            else:
                # JSONフォールバックには type_label が無いため、definition/funcを流用してマッピング
                for entry in parsed:
                    entry['type_label'] = ''
                    entry['content'] = entry.pop('definition')
                    entry['fact_check'] = entry.pop('func')

            for entry in parsed:
                type_label = entry['type_label']
                type_color = "bg-rose-100 text-rose-800" if "都市伝説" in type_label else "bg-teal-100 text-teal-800"
                type_badge = f'<span class="{type_color} px-2 py-1 rounded text-xs">{html.escape(type_label)}</span>' if type_label else ''

                cases_html = ""
                for ctx, expr, ana in entry['cases']:
                    if expr:
                        cases_html += f'''
                        <div class="bg-slate-50 p-3 rounded-lg border border-slate-200 shadow-sm">
                            <div class="text-xs font-bold text-slate-500 mb-1">状況: {html.escape(ctx)}</div>
                            <div class="text-sm text-slate-800 font-bold mb-2">表現: {html.escape(expr)}</div>
                            <div class="text-xs text-slate-600 bg-white p-2 rounded border border-slate-100">分析: {html.escape(ana)}</div>
                        </div>
                        '''

                country_parts.append(f'''
                <details class="group/item bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                    <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                        <span class="flex items-center gap-2">
                            {type_badge}
                            <span class="text-xs font-mono text-teal-700 bg-teal-100 px-2 py-1 rounded">{html.escape(entry['quad'])}</span>
                            {html.escape(entry['name'])}
                        </span>
                        <span class="text-slate-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
                    </summary>
                    <div class="p-4 border-t border-slate-100 bg-white space-y-4">
                        <div class="mb-2">
                            <h5 class="text-xs font-bold text-slate-400 mb-1">信じられている内容</h5>
                            <p class="text-sm text-slate-700 leading-relaxed">{html.escape(entry['content'])}</p>
                        </div>
                        <div class="bg-amber-50 p-3 rounded text-sm text-slate-800 border border-amber-200 mb-4">
                            <span class="font-bold text-amber-700">[事実確認] 学術的背景・反証:</span> {html.escape(entry['fact_check'])}
                        </div>
                        <div>
                            <h5 class="text-xs font-bold text-teal-800 mb-2 border-b border-teal-100 pb-1 flex items-center gap-1">📚 事例・ケーススタディ</h5>
                            <div class="grid grid-cols-1 gap-3">
                                {cases_html}
                            </div>
                        </div>
                    </div>
                </details>
                ''')
        country_parts.append("</div></details>")
        country_blocks.append(f'<div id="country-data-{html.escape(country)}" style="display:none;">' + "".join(country_parts) + '</div>')

    html_parts = [map_and_display_html] + country_blocks
    return "".join(html_parts)

def compile_data():
    compiled = []
    print("⏳ [1/2] 『その他の学術分野での研究』 のコンパイルを実行中...")
    html_others = build_research_others()
    
    for target_id in TARGET_IDS:
        content = ""
        # 1. 独立パーサがあるもの
        if target_id == "research_others":
            content = html_others
        elif target_id == "research_physiology":
            content = build_research_physiology()
        elif target_id == "culture_japan":
            content = build_culture_japan()
        elif target_id == "culture_world_academic":
            content = build_culture_world_academic_v3()
        elif target_id == "culture_world_survey":
            content = build_culture_world_survey_v3()

        # 2. HTMLから抽出するもの
        elif target_id in ["basic-form", "academic-definition", "dictionary-comparison"]:
            extracted = extract_html_block("tab-definition.html", target_id)
            if extracted:
                content = extracted
        elif target_id in ["evolution-academic", "evolution-comic"]:
            extracted = extract_html_block("tab-culture.html", target_id)
            if extracted:
                content = extracted
            
        # 3. フォールバック（プレースホルダー）
        if not content:
            content = f"<div class='p-6 bg-slate-50 rounded-xl shadow-inner border border-slate-200 text-center'><h2 class='text-lg font-bold text-slate-400 mb-2'>ID: {target_id}</h2><p class='text-slate-500 text-sm'>現在データをコンパイル中です。次のフェーズで解放されます。</p></div>"
        
        compiled.append({
            "id": target_id,
            "content": content
        })
    return compiled

def build():
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    data = compile_data()
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':')) # 容量削減のため最小化
    file_size = OUTPUT_JSON.stat().st_size
    print(f"✅ [2/2] JSONビルド完了: {OUTPUT_JSON.name} ({file_size} bytes)")

if __name__ == "__main__":
    build()
