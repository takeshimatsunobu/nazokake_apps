import os, re

filepath = 'build_research_data.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# v2からv3へルーティング変更
content = content.replace('build_culture_world_academic_v2()', 'build_culture_world_academic_v3()')
content = content.replace('build_culture_world_survey_v2()', 'build_culture_world_survey_v3()')

v3_funcs = """
def build_culture_world_academic_v3():
    rows = read_csv_skip("041世界の言語活動調査.(学術的).csv", skip_lines=1)
    if not rows: return "<div class='p-4 text-slate-500'>データがありません。</div>"
    
    # 全体説明（A）のHTML
    intro_html = '''
    <div class="bg-gradient-to-br from-slate-900 to-indigo-950 text-white p-6 md:p-8 rounded-2xl shadow-xl mb-12 border border-indigo-500/30">
        <h2 class="text-2xl md:text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-300 mb-8 border-b border-indigo-500/50 pb-4">
            🌍 世界の言語文化：コミュニケーションの4象限モデル
        </h2>

        <!-- 1. 軸の解説 -->
        <section class="mb-10">
            <h3 class="text-xl font-bold text-emerald-300 mb-4 flex items-center gap-2"><span class="text-2xl">🧭</span> 1. 分類の「理屈」：コミュニケーションを分ける2つの軸</h3>
            <p class="text-indigo-100 leading-relaxed mb-6 text-sm md:text-base">人間の言葉は無数にあるように見えて、実は「相手との関係をどうしたいか（目的）」と「言葉をどう使うか（手段）」の2つの軸でMECE（漏れなくダブりなく）に4つの象限に整理できます。</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="bg-white/5 p-5 rounded-xl border border-white/10 backdrop-blur-sm">
                    <h4 class="font-bold text-blue-300 mb-3 text-lg border-b border-blue-500/30 pb-2">↕️ 縦軸（関係性のベクトル）</h4>
                    <ul class="space-y-3 text-sm text-indigo-50">
                        <li class="flex gap-2"><span class="font-bold text-blue-400 w-16 shrink-0">【協調】</span> <span>相手と結びつきたい、社会の平穏を維持したい、仲間になりたい。</span></li>
                        <li class="flex gap-2"><span class="font-bold text-rose-400 w-16 shrink-0">【対立】</span> <span>相手とぶつかりたい、不満を伝えたい、自分の正しさを証明したい。</span></li>
                    </ul>
                </div>
                <div class="bg-white/5 p-5 rounded-xl border border-white/10 backdrop-blur-sm">
                    <h4 class="font-bold text-amber-300 mb-3 text-lg border-b border-amber-500/30 pb-2">↔️ 横軸（表現のモード）</h4>
                    <ul class="space-y-3 text-sm text-indigo-50">
                        <li class="flex gap-2"><span class="font-bold text-amber-400 w-20 shrink-0">【直接的】</span> <span>効率重視。事実や論理をストレートに伝える（コスパ・正論）。</span></li>
                        <li class="flex gap-2"><span class="font-bold text-purple-400 w-20 shrink-0">【間接的】</span> <span>遊び重視。比喩、隠語、ユーモア、ルール（制約）のフィルターを通す。</span></li>
                    </ul>
                </div>
            </div>
        </section>

        <!-- 2. 象限ごとの意味 -->
        <section class="mb-10">
            <h3 class="text-xl font-bold text-emerald-300 mb-4 flex items-center gap-2"><span class="text-2xl">🧩</span> 2. 各象限の意味（人間社会における機能）</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                <!-- Q1 -->
                <div class="bg-slate-800/80 p-5 rounded-xl border-t-4 border-blue-500 hover:bg-slate-800 transition">
                    <h4 class="font-bold text-blue-400 mb-1 text-lg">第1象限：秩序と伝達</h4>
                    <p class="text-xs text-blue-200/70 mb-3 font-mono">直接的 × 協調</p>
                    <p class="text-sm text-blue-100 font-bold mb-3 pb-2 border-b border-slate-700">社会の歯車を摩擦なく回すための「潤滑油」</p>
                    <p class="text-sm text-slate-300 mb-2"><span class="text-slate-500">具体例:</span> マニュアル敬語、定型文、ポリコレ、タブー</p>
                    <p class="text-sm text-slate-300 leading-relaxed mb-3"><span class="text-slate-500">機能:</span> 距離や上下関係を明確にし「波風を立てないこと」を最優先。見知らぬ人とも安全に生活できる。</p>
                    <div class="bg-blue-950/50 p-3 rounded text-sm text-blue-200 border border-blue-900/50">
                        <span class="font-bold text-rose-400">⚠️ ペイン:</span> 炎上を恐れ肥大化。本音が言えず言葉狩りに怯える「AIのような無難な言葉」が現代人に息苦しさを与える。
                    </div>
                </div>
                <!-- Q2 -->
                <div class="bg-slate-800/80 p-5 rounded-xl border-t-4 border-amber-500 hover:bg-slate-800 transition">
                    <h4 class="font-bold text-amber-400 mb-1 text-lg">第2象限：共感と審美</h4>
                    <p class="text-xs text-amber-200/70 mb-3 font-mono">間接的 × 協調</p>
                    <p class="text-sm text-amber-100 font-bold mb-3 pb-2 border-b border-slate-700">「私たち」という居場所を作る「暗号と見立て」</p>
                    <p class="text-sm text-slate-300 mb-2"><span class="text-slate-500">具体例:</span> 若者言葉、ネットスラング、詩的な比喩、女房言葉</p>
                    <p class="text-sm text-slate-300 leading-relaxed mb-3"><span class="text-slate-500">機能:</span> あえて別の言葉に変換し、解読できた者同士の間にアハ体験と深い連帯感を生み出す。</p>
                    <div class="bg-amber-950/50 p-3 rounded text-sm text-amber-200 border border-amber-900/50">
                        <span class="font-bold text-emerald-400">💡 インサイト:</span> なぞかけの面白さの源泉（UXのコア）は、まさにこの「見立てによる脳の快感」にある。
                    </div>
                </div>
                <!-- Q3 -->
                <div class="bg-slate-800/80 p-5 rounded-xl border-t-4 border-rose-500 hover:bg-slate-800 transition">
                    <h4 class="font-bold text-rose-400 mb-1 text-lg">第3象限：論争と闘争</h4>
                    <p class="text-xs text-rose-200/70 mb-3 font-mono">直接的 × 対立</p>
                    <p class="text-sm text-rose-100 font-bold mb-3 pb-2 border-b border-slate-700">相手を屈服させ、社会を分断する「刃（やいば）」</p>
                    <p class="text-sm text-slate-300 mb-2"><span class="text-slate-500">具体例:</span> SNSでのレスバ、キャンセルカルチャー、誹謗中傷</p>
                    <p class="text-sm text-slate-300 leading-relaxed mb-3"><span class="text-slate-500">機能:</span> 自分の正しさを証明し、論理や強い言葉で直接的に攻撃する。ディベートでの勝敗が重視される。</p>
                    <div class="bg-rose-950/50 p-3 rounded text-sm text-rose-200 border border-rose-900/50">
                        <span class="font-bold text-rose-400">⚠️ ペイン:</span> 勝敗がついても深い恨みを残す。エコーチェンバーと相まって、修復不可能な社会の分断と炎上を引き起こす。
                    </div>
                </div>
                <!-- Q4 -->
                <div class="bg-slate-800/80 p-5 rounded-xl border-t-4 border-purple-500 hover:bg-slate-800 transition">
                    <h4 class="font-bold text-purple-400 mb-1 text-lg">第4象限：対立の遊戯的昇華</h4>
                    <p class="text-xs text-purple-200/70 mb-3 font-mono">間接的 × 対立</p>
                    <p class="text-sm text-purple-100 font-bold mb-3 pb-2 border-b border-slate-700">争いを笑いと和解に変える「魔法のクッション」</p>
                    <p class="text-sm text-slate-300 mb-2"><span class="text-slate-500">具体例:</span> なぞかけ、イヌイットの即興詩バトル、冗談関係</p>
                    <p class="text-sm text-slate-300 leading-relaxed mb-3"><span class="text-slate-500">機能:</span> 怒りや対立を「ユーモア」やルールの枠に押し込む。暴力沙汰にならず和解できる、人類究極のサバイバル技術。</p>
                </div>
            </div>
        </section>

        <!-- 3. ストーリー -->
        <section class="bg-gradient-to-r from-emerald-900/80 to-teal-900/80 p-6 rounded-xl border border-emerald-400/30 shadow-lg relative overflow-hidden">
            <div class="absolute top-0 right-0 p-4 opacity-10 text-6xl">💊</div>
            <h3 class="text-xl font-bold text-emerald-300 mb-4 relative z-10">🚀 全体を貫くストーリー（なぜ今、なぞかけアプリなのか）</h3>
            <p class="text-sm md:text-base text-emerald-50 leading-relaxed relative z-10">
                現代のコミュニケーションは完全に壊れかけています。SNSでは、<strong>第3象限（論破と炎上）</strong>で血を流し合うか、それを恐れて<strong>第1象限（ポリコレや定型文）</strong>という無菌室に逃げ込み、息を潜めるかの二極化に陥っています。<br><br>
                しかし、人類は本来、怒りや対立を<strong>第4象限（ユーモアと制約のゲーム）</strong>に変換して安全にガス抜きする知恵を持っていました。そして、<strong>第2象限（見立てと暗号）</strong>を解読する快感によって仲間との深い絆を作ってきたのです。<br><br>
                なぞかけアプリは、ただの暇つぶしではありません。第1象限の息苦しさと第3象限の争いを抜け出し、第2象限の快感を用いながら、<strong>第4象限の機能（本音を笑いに変える安全弁）を現代のデジタル空間に再実装する、社会的な処方箋</strong>なのです。
            </p>
        </section>
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
        
    html_parts = [intro_html, "<div class='space-y-6'>"]
    
    # 対象国アコーディオン
    for country, items in grouped.items():
        html_parts.append(f'''
        <details class="group bg-white rounded-xl border border-indigo-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-indigo-50 font-bold text-indigo-900 flex justify-between items-center hover:bg-indigo-100 transition">
                <span class="flex items-center gap-2"><span class="text-2xl">🌍</span> {html.escape(country)}</span>
                <span class="text-indigo-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-indigo-50/30">
        ''')
        
        # 象限＋事象名アコーディオン
        for row in items:
            r = [col.strip() for col in row]
            quad, _, name, definition, structure, bg, func, effect, ex1_ctx, ex1_expr, ex1_ana, ex2_ctx, ex2_expr, ex2_ana, ex3_ctx, ex3_expr, ex3_ana = r[:17]
            
            # 事例カードの生成
            cases_html = ""
            for ctx, expr, ana in [(ex1_ctx, ex1_expr, ex1_ana), (ex2_ctx, ex2_expr, ex2_ana), (ex3_ctx, ex3_expr, ex3_ana)]:
                if expr:
                    cases_html += f'''
                    <div class="bg-slate-50 p-3 rounded-lg border border-slate-200 shadow-sm">
                        <div class="text-xs font-bold text-slate-500 mb-1">状況: {html.escape(ctx)}</div>
                        <div class="text-sm text-slate-800 font-bold mb-2">表現: {html.escape(expr)}</div>
                        <div class="text-xs text-slate-600 bg-white p-2 rounded border border-slate-100">分析: {html.escape(ana)}</div>
                    </div>
                    '''

            html_parts.append(f'''
            <details class="group/item bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                    <span class="flex items-center gap-2">
                        <span class="text-xs font-mono text-indigo-700 bg-indigo-100 px-2 py-1 rounded">{html.escape(quad)}</span>
                        {html.escape(name)}
                    </span>
                    <span class="text-slate-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
                </summary>
                <div class="p-4 border-t border-slate-100 bg-white space-y-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <h5 class="text-xs font-bold text-slate-400 mb-1">定義・言語構造</h5>
                            <p class="text-sm text-slate-700 leading-relaxed">{html.escape(definition)}</p>
                        </div>
                        <div>
                            <h5 class="text-xs font-bold text-slate-400 mb-1">社会的機能 / 心理的効果</h5>
                            <p class="text-sm text-slate-700 leading-relaxed">{html.escape(func)}</p>
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
            
        html_parts.append("</div></details>")
    html_parts.append("</div>")
    return "".join(html_parts)

def build_culture_world_survey_v3():
    rows = read_csv_skip("042 世界の言語活動調査(実態調査).csv", skip_lines=1)
    if not rows: return "<div class='p-4 text-slate-500'>データがありません。</div>"
    
    grouped = {}
    for row in rows:
        if len(row) < 17: continue
        quad = row[0].strip()
        country = row[1].strip()
        if country not in grouped: grouped[country] = []
        grouped[country].append(row)
        
    html_parts = ["<div class='space-y-6'>"]
    for country, items in grouped.items():
        html_parts.append(f'''
        <details class="group bg-white rounded-xl border border-teal-200 shadow-sm overflow-hidden mb-6">
            <summary class="cursor-pointer p-4 bg-teal-50 font-bold text-teal-900 flex justify-between items-center hover:bg-teal-100 transition">
                <span class="flex items-center gap-2"><span class="text-2xl">🌍</span> {html.escape(country)}</span>
                <span class="text-teal-500 group-open:rotate-180 transition-transform duration-300">▼</span>
            </summary>
            <div class="p-4 space-y-4 bg-teal-50/30">
        ''')
        for row in items:
            r = [col.strip() for col in row]
            quad, _, type_label, name, content, func, effect, fact_check, ex1_ctx, ex1_expr, ex1_ana, ex2_ctx, ex2_expr, ex2_ana, ex3_ctx, ex3_expr, ex3_ana = r[:17]
            
            type_color = "bg-rose-100 text-rose-800" if "都市伝説" in type_label else "bg-teal-100 text-teal-800"
            
            cases_html = ""
            for ctx, expr, ana in [(ex1_ctx, ex1_expr, ex1_ana), (ex2_ctx, ex2_expr, ex2_ana), (ex3_ctx, ex3_expr, ex3_ana)]:
                if expr:
                    cases_html += f'''
                    <div class="bg-slate-50 p-3 rounded-lg border border-slate-200 shadow-sm">
                        <div class="text-xs font-bold text-slate-500 mb-1">状況: {html.escape(ctx)}</div>
                        <div class="text-sm text-slate-800 font-bold mb-2">表現: {html.escape(expr)}</div>
                        <div class="text-xs text-slate-600 bg-white p-2 rounded border border-slate-100">分析: {html.escape(ana)}</div>
                    </div>
                    '''

            html_parts.append(f'''
            <details class="group/item bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                <summary class="cursor-pointer p-3 bg-slate-100 font-bold text-slate-800 flex justify-between items-center hover:bg-slate-200 transition">
                    <span class="flex items-center gap-2">
                        <span class="{type_color} px-2 py-1 rounded text-xs">{html.escape(type_label)}</span>
                        <span class="text-xs font-mono text-teal-700 bg-teal-100 px-2 py-1 rounded">{html.escape(quad)}</span>
                        {html.escape(name)}
                    </span>
                    <span class="text-slate-400 group-open/item:rotate-180 transition-transform duration-300">▼</span>
                </summary>
                <div class="p-4 border-t border-slate-100 bg-white space-y-4">
                    <div class="mb-2">
                        <h5 class="text-xs font-bold text-slate-400 mb-1">信じられている内容</h5>
                        <p class="text-sm text-slate-700 leading-relaxed">{html.escape(content)}</p>
                    </div>
                    <div class="bg-amber-50 p-3 rounded text-sm text-slate-800 border border-amber-200 mb-4">
                        <span class="font-bold text-amber-700">[事実確認] 学術的背景・反証:</span> {html.escape(fact_check)}
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
        html_parts.append("</div></details>")
    html_parts.append("</div>")
    return "".join(html_parts)
"""

if "def build_culture_world_academic_v3():" not in content:
    content = re.sub(r'(def compile_data\(\):)', v3_funcs + r'\n\1', content)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ 成功: 世界の言語文化（学術/実態調査）のV3パーサを実装しました。")
else:
    print("⚠️ 既に適用済みです。")