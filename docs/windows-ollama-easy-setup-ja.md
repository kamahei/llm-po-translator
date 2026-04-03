# Windows かんたんセットアップ（Ollama ローカル 1 モデル）

この手順は、**Windows で Ollama をローカル起動し、LLM を 1 つだけ使う** 前提の最短セットアップです。

`.env` は `config\config.example.env` のデフォルト設定をそのまま使います。

## Windows 標準環境で動くか

基本的には、**Windows 10 / 11 の標準的な PowerShell 5.1 環境で動きます**。

- `winget` / `choco` / `WSL` / Git Bash は不要です。
- 初回セットアップでは、Python 本体、Ollama 本体、Ollama モデルをダウンロードするので**インターネット接続が必要**です。
- 途中で Ollama のインストール確認や、Windows の長いパス設定のための確認画面が出ることがあります。
- 会社 PC などで、アプリのインストールやレジストリ変更がポリシーで制限されている場合は、その制限の影響を受けます。

## 必要な外部アプリ

- Python:
  セットアップスクリプトが、必要なら公式配布元から**最新の安定版 Python** を自動でインストールします。
- Ollama:
  セットアップスクリプトが、未導入なら自動でインストールします。

## 先に手動で入れたい場合

Python や Ollama は自動インストールできますが、**先に手動でインストールしてからセットアップを実行することも可能**です。

- 特定バージョンの Python を使いたい場合:
  先にその Python を手動で入れてからセットアップを実行できます。
- その場合は、**Python 3.9 以上**で、`python` と `py` が使える状態にしておくのが安全です。
- 標準的な Python インストーラーで `py` が入っていない状態だと、セットアップが最新の安定版 Python を追加で入れることがあります。
- Ollama も、先に手動インストールしてあれば、その既存インストールをそのまま使います。

## いちばん簡単なやり方

1. `POTranslatorLLM` フォルダーを開きます。
2. `Start-Windows-Ollama-Setup.cmd` をダブルクリックします。
3. 途中で Ollama / Python / Windows の確認画面が出たら許可して、`Setup complete!` と表示されるまで待ちます。

もし Windows 11 の `Smart App Control` が `Start-Windows-Ollama-Setup.cmd` を止めたら、PowerShell を開いて、先に `POTranslatorLLM` フォルダーへ移動してから次を実行してください。

```powershell
cd <POTranslatorLLM を展開したフォルダー>
Unblock-File .\Start-Windows-Ollama-Setup.cmd
Unblock-File .\setup\install-ollama-local.ps1
.\Start-Windows-Ollama-Setup.cmd
```

`.zip` でダウンロードした場合は、展開前に `.zip` を右クリックして `プロパティ` を開き、`ブロックの解除` を付けてから展開すると止められにくくなります。

この 1 回で、次の作業が自動で終わります。

- Ollama のインストール確認
- Ollama の起動確認
- 既定モデル `qwen2.5:7b` のダウンロード
- 最新の安定版 Python のインストール（未導入または古い場合）
- `python` / `py` / Python の `Scripts` フォルダーを `PATH` に追加
- Windows の長いパス設定 (`LongPathsEnabled`) を有効化
- Python 依存関係のインストール
- `.env` の作成（`config\config.example.env` からコピー）

## `.env` について

`.env` はそのままで大丈夫です。ローカル PC で 1 モデルだけ使うなら、初期設定のままで動きます。

すでに `.env` がある場合は、その内容が優先されます。初期設定に戻したいときだけ、`.env` を削除してからもう一度 `Start-Windows-Ollama-Setup.cmd` を実行してください。

## セットアップ後の確認

まずは動作確認だけ行います。

`Localization/Game` はサンプルのパスです。自分が翻訳したい `.po` ファイルが入っているフォルダーのパスに置き換えてください。

```powershell
python scripts\translate.py --folder Localization/Game --source-lang ja --target-lang en --dry-run
```

問題なければ、そのまま翻訳を実行します。

```powershell
python scripts\translate.py --folder Localization/Game --source-lang ja --target-lang en
```

## うまくいかないとき

- 初回はモデルのダウンロードに時間がかかります。
- 途中で失敗した場合は、表示された内容を確認して同じファイルをもう一度ダブルクリックしてください。
- Windows 11 の `Smart App Control` に止められる場合は、上の `Unblock-File` 手順を使ってください。
- Python の確認画面が出たら、**そのまま許可してください**。セットアップスクリプトが公式配布元から最新の安定版 Python を自動で入れます。
- `Disable path length limit` を手で押す必要はありません。セットアップスクリプトが `LongPathsEnabled` を自動で有効化します。
- `python` や `py` がすぐ使えない場合は、新しい PowerShell / コマンドプロンプトを開き直してください。
- 長いパス設定の権限昇格をキャンセルした場合は、その部分だけ有効にならないので、もう一度セットアップを実行して許可してください。

## 関連ファイル

- ダブルクリック用セットアップ: `Start-Windows-Ollama-Setup.cmd`
- 詳細マニュアル: `docs\user-manual.md`
