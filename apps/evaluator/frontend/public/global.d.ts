// CDN経由(<script>タグ)で読み込まれ、npmパッケージとしては存在しないグローバルの
// アンビエント宣言。型情報までは追わず`any`扱いにすることで、checkJs対象ファイルが
// これらの参照だけで型エラーになるのを防ぐ。
//
// FirebaseUI 6.1.0にESM版が存在しないため、admin.jsのFirebase Auth(compat)/FirebaseUIは
// 引き続きこれらのグローバルを参照する(ESM化の対象外。詳細はplan参照)。
declare const firebase: any;
declare const firebaseui: any;
declare const Chart: any;
declare const html2canvas: any;
