import os
import json
import urllib.request
import time

def gather_evidence():
    print("\n================ [ ファクト収集: デプロイ・パイプラインの真相究明 ] ================")

    # --------------------------------------------------
    # 証拠2: デプロイ先ディレクトリの真実 (firebase.json)
    # --------------------------------------------------
    print("\n🔍 [証拠2] firebase.json の公開ディレクトリ設定:")
    public_dir = None
    if os.path.exists("firebase.json"):
        try:
            with open("firebase.json", "r", encoding="utf-8") as f:
                fb_data = json.load(f)
                public_dir = fb_data.get("hosting", {}).get("public")
                if public_dir:
                    print(f"  👉 Firebaseが本番に上げているフォルダ: 【 {public_dir} 】")
                else:
                    print("  👉 publicディレクトリの指定が見つかりません。")
        except Exception as e:
            print(f"  🚨 読み込みエラー: {e}")
    else:
        print("  ⚠️ firebase.json が見つかりません。")

    # --------------------------------------------------
    # 証拠3: ビルド工程の真実 (package.json)
    # --------------------------------------------------
    print("\n🔍 [証拠3] package.json のビルド工程 (npm run build):")
    if os.path.exists("package.json"):
        try:
            with open("package.json", "r", encoding="utf-8") as f:
                pkg_data = json.load(f)
                build_script = pkg_data.get("scripts", {}).get("build")
                if build_script:
                    print(f"  👉 ビルドコマンドが存在します: 【 {build_script} 】")
                    print("     (※デプロイ前に npm run build を実行する必要があるプロジェクトです)")
                else:
                    print("  👉 ビルドコマンドは未設定です (ビルド不要の可能性大)。")
        except Exception as e:
            print(f"  🚨 読み込みエラー: {e}")
    else:
        print("  👉 package.json が見つかりません。(ビルド不要の純粋なHTML/JS構成と推測されます)")

    # --------------------------------------------------
    # 証拠1: 本番サーバー(URL)に上がっているコードの実態
    # --------------------------------------------------
    print("\n🔍 [証拠1] 本番サーバー上のコード実態:")
    print("  ... Googleのサーバー(nazokakeapp-137e5.web.app)に直接アクセスして中身を確認中...")
    
    # URLにランダムな数字(タイムスタンプ)をつけて、CDNのキャッシュを強制的に突破する
    url = f"https://nazokakeapp-137e5.web.app/app_final.js?v={int(time.time())}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            live_code = response.read().decode('utf-8')
            
            if "total_score" in live_code:
                print("  👉 判定: 新しいコード (total_score) が【本番に届いています】！")
                print("     💡 結論: デプロイは成功しています。Takeshiさんのブラウザのキャッシュが強すぎることが唯一の原因です。")
            elif "s_total" in live_code:
                print("  👉 判定: 本番のコードは古いまま (s_total のみ) です。")
                if public_dir and public_dir != "frontend":
                    print(f"     💡 結論: 私たちが修正した 'frontend' フォルダと、Firebaseがアップロードした '{public_dir}' フォルダがズレている「デプロイ空振り」が原因です。")
                else:
                    print("     💡 結論: 修正パッチがうまく当たっていないか、ビルド漏れが原因です。")
            else:
                print("  👉 判定: どちらの変数名も見つかりませんでした。別のファイルで処理されている可能性があります。")
    except urllib.error.URLError as e:
        print(f"  🚨 本番URLからの取得に失敗しました (404 Not Found等の場合、ファイル名やパスが違う可能性があります): {e}")
    except Exception as e:
         print(f"  🚨 本番URLからの取得中に予期せぬエラーが発生しました: {e}")

    print("\n=========================================================================")

if __name__ == "__main__":
    gather_evidence()
