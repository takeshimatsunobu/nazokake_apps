// API_BASEは全フロントエンドJSにとっての唯一のSSoT。ローカルのポート番号(run_api.ps1 /
// start_dev.ps1 の実際のuvicorn起動先と一致させる)を他ファイルへ複製すると、どちらかだけ
// 変更されて食い違う構成ドリフトを起こす(実際に発生した不具合: ここが7800のまま、
// バックエンドは8000で起動していてadmin.js/main_index.js経由の通信がERR_CONNECTION_REFUSED
// になった)。admin.js/main_index.js はこの定数をimportして使い、値を複製しない。
export const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';
export const APP_URL = "https://nazokakeapp-137e5.web.app/";
