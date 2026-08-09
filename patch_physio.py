import os, re

filepath = 'build_research_data.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# より安全なV2関数へルーティングを切り替え
content = content.replace('build_research_physiology()', 'build_research_physiology_v2()')

v2_funcs = """
def build_research_physiology_v2():
    rows = read_csv_skip("021 なぞかけの生理学的な研究(JSON).csv", skip_lines=2)
    if not rows:
        return "<div class='p-4 text-slate-500'>データがありません。</div>"
    
    grouped = {}
    for row in rows:
        if len(row) < 9: continue
        item_id, cat, chap, title, exp, rel, b_title, b_year, b_res = [r.strip() for r in row[:9]]
        if not title: continue
        
        if cat not in grouped: grouped[cat] = {}
        if chap not in grouped[cat]: grouped[cat][chap] = []
        
        grouped[cat][chap].append({
            "id": item_id, "title": title, "exp": exp, "rel": rel,
            "b_title": b_title, "b_year": b_year, "b_res": b_res
        })
        
    html_parts = ["<div class='space-y-6'>"]
    for cat, chaps in grouped.items():
        html_parts.append(f'''
        <details class="group bg-white rounded-xl border border-emerald-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-emerald-50 font-bold text-emerald-900 flex justify-between items-center hover:bg-emerald-100 transition">
                <span class="flex items-center gap-2"><span class="text-xl">🏛️</span> {html.escape(cat)}</span>
                <span class="text-emerald-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-emerald-50/30">
        ''')
        
        for chap, items in chaps.items():
            html_parts.append(f'''
            <details class="group/chap bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                    <span class="flex items-center gap-2"><span class="text-lg">📖</span> {html.escape(chap)}</span>
                    <span class="text-slate-400 group-open/chap:rotate-180 transition-transform duration-300">▼</span>
                </summary>
                <div class="p-4 grid grid-cols-1 gap-4 bg-slate-50">
            ''')
            
            for item in items:
                html_parts.append(f'''
                <article class='bg-white rounded-xl p-5 shadow-sm border border-slate-200 hover:shadow-md transition-shadow'>
                    <h4 class='text-lg font-bold text-emerald-800 mb-3 flex items-center gap-2'>
                        <span class='text-xs font-mono text-emerald-700 bg-emerald-100 px-2 py-1 rounded'>{html.escape(item["id"])}</span>
                        🧠 {html.escape(item["title"])}
                    </h4>
                    <div class='mb-4'><h5 class='text-xs font-bold text-slate-400 mb-1'>実験・結果</h5><p class='text-sm text-slate-700 leading-relaxed'>{html.escape(item["exp"])}</p></div>
                    <div class='mb-4'><h5 class='text-xs font-bold text-slate-400 mb-1'>なぞかけとの関係</h5><p class='text-sm text-slate-700 leading-relaxed'>{html.escape(item["rel"])}</p></div>
                    <div class='bg-slate-100 p-3 rounded-lg text-xs text-slate-500 border border-slate-200'>
                        📚 <strong>{html.escape(item["b_title"])}</strong> ({html.escape(item["b_year"])})<br>👤 {html.escape(item["b_res"])}
                    </div>
                </article>
                ''')
            
            html_parts.append("</div></details>")
        html_parts.append("</div></details>")
    html_parts.append("</div>")
    return "".join(html_parts)
"""

if "def build_research_physiology_v2():" not in content:
    content = re.sub(r'(def compile_data\(\):)', v2_funcs + r'\n\1', content)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ 成功: 生理学的研究のV2パーサ（2階層アコーディオン完全版）を実装しました。")
else:
    print("⚠️ 既に適用済みです。")