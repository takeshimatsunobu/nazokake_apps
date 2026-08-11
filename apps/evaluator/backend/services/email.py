"""services/email.py
=====================
メール送信ロジック(内製化・Phase 0)。

Firebase Extensions「Trigger Email」は非推奨警告が出たため採用を見送り、標準ライブラリの
smtplib + email.mime のみでGmail SMTP経由の送信を行う。外部SaaS(SendGrid等)への新規契約も
不要で、依存パッケージの追加もゼロ(標準ライブラリのみ)。

【認証情報】環境変数 SMTP_USER(送信元Gmailアドレス) / SMTP_PASSWORD(Googleアカウントの
アプリパスワード。通常のログインパスワードではない。Googleアカウント設定 > セキュリティ >
2段階認証 > アプリパスワード から発行する16桁の文字列)を使用する。

【呼び出し方針】この関数群はすべて同期(ブロッキングI/O)。api/routers/admin_auth.py からは
必ず BackgroundTasks 経由で呼び出すこと(FastAPI/StarletteのBackgroundTaskは同期callableを
自動的にスレッドプール(run_in_threadpool)で実行するため、イベントループはブロックしない。
ただしリクエスト処理そのものと直列に呼ぶとSMTP往復分だけレスポンスが遅延するため、それを
避けるためにBackgroundTasks化が必須)。

【送信失敗時の扱い】ここでは例外を握りつぶさない(呼び出し元のBackgroundTasksが例外を
ログへ記録する仕組みに委ねる)。招待そのもの(Firestoreへの書き込み)はメール送信の成否に
関わらず既に完了しているため、メール送信が失敗してもユーザー体験としては「招待リンクを
運営から直接共有する」という代替手段が残る(致命的な機能停止にはならない)。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
# 465(SMTP over SSL、接続時点で暗号化が確立済み)を既定とする。587(STARTTLS)を使いたい
# 場合は環境変数 SMTP_PORT で上書きできるようにしておく(既定は465固定で運用コスト最小)。
SMTP_PORT_SSL = 465


def _smtp_credentials() -> tuple[str, str]:
    """環境変数からSMTP認証情報を取得する。未設定時は明示的に例外を送出する
    (メール送信が必要な操作なのに黙って何もしない、という事故を防ぐ)。
    """
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not user or not password:
        raise ValueError(
            "SMTP_USER/SMTP_PASSWORD が環境変数に設定されていません"
            "(Gmailのアプリパスワードを発行し、両方を.env/Cloud Runの環境変数へ設定してください)"
        )
    return user, password


def send_email(to: str, subject: str, html_body: str) -> None:
    """Gmail SMTP(465, SSL)経由でHTMLメールを1通送信する(同期・ブロッキング)。"""
    user, password = _smtp_credentials()

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = user
    message["To"] = to
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL) as server:
        server.login(user, password)
        server.sendmail(user, [to], message.as_string())


def send_invite_email(to: str, invite_url: str) -> None:
    """管理者招待メール。招待された本人へ、招待URL(トークン付き)を送る。"""
    subject = "【なぞかけ管理コクピット】管理者への招待"
    html_body = f"""\
<div style="font-family: sans-serif; line-height: 1.7;">
  <p>なぞかけ管理コクピットの管理者として招待されました。</p>
  <p>以下のリンクを開き、Googleアカウントでログインしてください
  (このリンクの有効期限は発行から7日間です):</p>
  <p><a href="{invite_url}">{invite_url}</a></p>
  <p>ログイン後、メイン管理者の承認が完了するまでは操作できません。承認完了まで今しばらくお待ちください。</p>
  <p style="color:#888; font-size:12px;">心当たりが無い場合はこのメールを破棄してください。</p>
</div>"""
    send_email(to, subject, html_body)


def send_approval_request_email(owner_email: str, applicant_email: str, uid: str) -> None:
    """承認依頼メール。招待された人がログインを完了した直後、メイン管理者(オーナー)へ送る。"""
    subject = "【なぞかけ管理コクピット】新規承認依頼"
    html_body = f"""\
<div style="font-family: sans-serif; line-height: 1.7;">
  <p><strong>{applicant_email}</strong> さんが管理コクピットへのアクセスを申請しました。</p>
  <p>UID: {uid}</p>
  <p>管理コクピットの「Ⅴ 運用基盤」タブにある「承認待ち管理者」一覧から承認してください。</p>
</div>"""
    send_email(owner_email, subject, html_body)
