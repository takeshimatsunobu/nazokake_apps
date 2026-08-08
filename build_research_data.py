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
        _, cat, chap, title, exp, rel, b_title, b_year, b_res = [r.strip() for r in row]
        if not title:
            continue

        article = f'''
        <article class='bg-white rounded-xl p-5 shadow-sm border border-slate-200'>
            <h4 class='text-lg font-bold text-emerald-800 mb-3'>🧠 {html.escape(title)}</h4>
            <div class='mb-4'><h5 class='text-xs font-bold text-slate-400 mb-1'>実験・結果</h5><p class='text-sm text-slate-700'>{html.escape(exp)}</p></div>
            <div class='mb-4'><h5 class='text-xs font-bold text-slate-400 mb-1'>なぞかけとの関係</h5><p class='text-sm text-slate-700'>{html.escape(rel)}</p></div>
            <div class='bg-slate-50 p-2 rounded text-xs text-slate-500'>
                📚 {html.escape(b_title)} ({html.escape(b_year)}) - {html.escape(b_res)}
            </div>
        </article>
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
    
    html_parts = ["<div class='space-y-8'>"]
    for row in rows:
        if len(row) < 11:
            continue
        name, era, desc, actors, bg, atk, def_reply, point, terms, ref, _ = [r.strip() for r in row]
        if not name:
            continue
        
        html_parts.append(f'''
        <div class='bg-white rounded-xl p-6 shadow-sm border border-rose-200'>
            <h3 class='text-xl font-bold text-rose-800 mb-2'>🎌 {html.escape(name)} <span class='text-sm font-normal text-slate-500'>({html.escape(era)})</span></h3>
            <p class='text-sm text-slate-700 mb-4'>{html.escape(desc)}</p>
            <div class='grid grid-cols-1 md:grid-cols-2 gap-4 mb-4'>
                <div class='bg-rose-50 p-3 rounded'>
                    <h5 class='text-xs font-bold text-rose-700 mb-1'>🗡️ 攻撃 (状況)</h5>
                    <p class='text-sm'>{html.escape(atk)}</p>
                </div>
                <div class='bg-blue-50 p-3 rounded'>
                    <h5 class='text-xs font-bold text-blue-700 mb-1'>🛡️ 切り返し</h5>
                    <p class='text-sm'>{html.escape(def_reply)}</p>
                </div>
            </div>
            <div class='bg-amber-50 p-3 rounded text-sm text-slate-800 border border-amber-200'>
                <span class='font-bold text-amber-700'>評価ポイント:</span> {html.escape(point)}
            </div>
        </div>
        ''')
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
        
    # 2. Tailwind HTMLの生成
    html_parts = ["<div class='research-others-container space-y-16'>"]
    for cat, cat_data in grouped.items():
        html_parts.append("<section class='category-block'>")
        html_parts.append(f"<h2 class='text-2xl md:text-3xl font-extrabold text-slate-800 border-b-4 border-emerald-600 pb-3 mb-4'>{html.escape(cat)}</h2>")
        if cat_data['desc']:
            html_parts.append(f"<p class='text-slate-600 mb-8 leading-relaxed bg-emerald-50/50 p-4 rounded-lg text-sm md:text-base border border-emerald-100'>{html.escape(cat_data['desc']).replace(chr(10), '<br>')}</p>")
        
        for chap, items in cat_data['chapters'].items():
            html_parts.append("<div class='chapter-block mt-10 ml-0 md:ml-4'>")
            html_parts.append(f"<h3 class='text-xl font-bold text-slate-700 mb-6 flex items-center gap-2'><span class='text-emerald-500'>■</span> {html.escape(chap)}</h3>")
            html_parts.append("<div class='grid grid-cols-1 gap-6'>")
            
            for item in items:
                html_parts.append(f"""
                <article class='bg-white rounded-xl p-5 md:p-6 shadow-sm border border-slate-200 hover:shadow-md transition-shadow'>
                    <h4 class='text-lg font-bold text-slate-800 border-b pb-3 mb-4 flex items-center gap-3'>
                        <span class='text-xs font-mono text-emerald-700 bg-emerald-100 px-2 py-1 rounded'>{html.escape(item['id'])}</span>
                        <span>{html.escape(item['title'])}</span>
                    </h4>
                    <div class='mb-5'>
                        <h5 class='text-xs font-bold text-slate-400 tracking-wider mb-2 uppercase flex items-center gap-1'>🔬 分析・実験</h5>
                        <p class='text-slate-700 leading-relaxed text-sm'>{html.escape(item['analysis']).replace(chr(10), '<br>')}</p>
                    </div>
                    <div class='mb-5 p-4 bg-amber-50/70 rounded-lg border border-amber-100'>
                        <h5 class='text-xs font-bold text-amber-700 tracking-wider mb-2 uppercase flex items-center gap-1'>🧩 なぞかけとの関係</h5>
                        <p class='text-slate-800 leading-relaxed text-sm'>{html.escape(item['relation']).replace(chr(10), '<br>')}</p>
                    </div>
                    <div class='bg-slate-50 p-3 rounded-lg text-xs text-slate-500 border border-slate-200 flex flex-col gap-1'>
                        <div class='font-bold text-slate-600 flex items-center gap-1'>📚 論拠・出典研究</div>
                        <div class='italic'>『{html.escape(item['b_title'])}』</div>
                        <div class='flex flex-wrap gap-4 mt-1'>
                            <span class='bg-white px-2 py-0.5 rounded border border-slate-200'>🗓 {html.escape(item['b_year'])}</span>
                            <span class='bg-white px-2 py-0.5 rounded border border-slate-200'>👤 {html.escape(item['b_res'])}</span>
                        </div>
                    </div>
                </article>
                """)
            html_parts.append("</div></div>")
        html_parts.append("</section>")
    html_parts.append("</div>")
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
            content = build_culture_world_academic()
        elif target_id == "culture_world_survey":
            content = build_culture_world_survey()

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
