"""
GlobalMatch Assistant - UI翻訳辞書
日本語 / English の切り替えに使用
"""

TRANSLATIONS = {
    "ja": {
        # ===== Header =====
        "app_title": "# GlobalMatch Assistant",
        "app_subtitle": "*外国人エンジニア × 日本企業をつなぐ人材紹介業務効率化ツール*",
        "app_name": "GlobalMatch Assistant",
        "app_tagline": "外国人エンジニア × 日本企業をつなぐ人材紹介業務効率化ツール",

        # ===== Sidebar =====
        "settings": "設定",
        "lang_label": "Language / 言語",
        "api_key_label": "Groq API Key",
        "api_key_placeholder": "gsk_...",
        "api_key_help": "APIキーは[Groq Console](https://console.groq.com/keys)から無料で取得できます",
        "api_key_set": "✅ APIキー設定済み（secrets）",
        "gemini_fallback_label": "🔄 Gemini APIキー（フォールバック・任意）",
        "gemini_fallback_placeholder": "Gemini API Key",
        "gemini_fallback_help": "設定するとGroqがレート制限に達したとき自動でGemini 2.5 Flashに切り替わります。[Google AI Studio](https://aistudio.google.com/app/apikey) で取得可能",
        "gemini_fallback_active": "Gemini フォールバック有効",
        "no_history": "履歴がありません",
        "import_hint": "バックアップファイルをお持ちの場合、ここからインポートできます",
        "backup_file": "バックアップファイル（JSON）",
        "backup_file_help": "過去にエクスポートしたバックアップファイルを選択",
        "restore_btn": "復元する",
        "file_read_error": "ファイル読み込みエラー: {error}",
        "feature_select": "機能選択",
        "feature_select_label": "変換モードを選択",
        "feature_select_help": "変換したいドキュメントの種類を選択してください",

        # ===== Feature Names =====
        "feature.resume_optimize": "レジュメ最適化（英→日）",
        "feature.resume_anonymize": "レジュメ匿名化（英→英）",
        "feature.resume_pii": "レジュメ個人情報削除",
        "feature.jd_jp_en": "求人票魅力化（日→英）",
        "feature.jd_en_jp": "求人票翻訳（英→日）",
        "feature.jd_jp_jp": "求人票フォーマット化（日→日）",
        "feature.jd_en_en": "求人票フォーマット化（英→英）",
        "feature.jd_anonymize": "求人匿名化",
        "feature.company_intro": "企業紹介文作成（PDF）",
        "feature.matching": "レジュメ×求人票マッチング分析",
        "feature.cv_extract": "CV提案コメント抽出",
        "feature.email": "求人打診メール作成",
        "feature.batch": "バッチ処理（複数レジュメ）",

        # ===== Feature Category Labels =====
        "feature_cat_resume": "レジュメ",
        "feature_cat_jd": "求人票",
        "feature_cat_analysis": "分析・ツール",

        # ===== Onboarding =====
        "onboarding_title": "はじめての方へ",
        "onboarding_body": "「サンプル」ボタンでサンプルデータを読み込んで、すぐに機能を試せます。左側のサイドバーから使いたい機能を選択してください。",
        "onboarding_dismiss": "閉じる",

        # ===== Usage Guide =====
        "usage_guide": "使い方",
        "usage_guide_content": """
            **レジュメ最適化（英→日）**
            1. 英語のレジュメをペーストまたはPDFをアップロード
            2. 匿名化オプションを設定
            3. 「変換実行」をクリック

            **レジュメ匿名化（英→英）**
            1. 英語のレジュメをペーストまたはPDFをアップロード
            2. 匿名化レベルを選択
            3. 英語のまま匿名化されたレジュメを取得

            **レジュメ個人情報削除**
            1. レジュメをペーストまたはPDFをアップロード
            2. 「個人情報削除実行」をクリック
            3. メール・LinkedIn・電話番号・住所が削除され、氏名がFirst nameのみに変更されたレジュメを取得

            **求人票魅力化（日→英）**
            1. 日本語の求人票をペースト
            2. 「変換実行」をクリック

            **求人票翻訳（英→日）**
            1. 英語の求人票をペースト
            2. 「変換実行」をクリック
            3. 日本人エンジニア向けに最適化

            **求人票フォーマット化（日→日）**
            1. 日本語の求人票をペースト
            2. 「変換実行」をクリック
            3. 統一フォーマットの魅力的な日本語JDを取得

            **求人票フォーマット化（英→英）**
            1. 英語の求人票をペースト
            2. 「変換実行」をクリック
            3. 統一フォーマットの魅力的な英語JDを取得

            **企業紹介文作成（PDF）**
            1. 会社紹介PDFをアップロード
            2. 「紹介文作成」をクリック
            3. 求職者向けの簡潔な企業紹介文を取得

            **レジュメ×求人票マッチング分析**
            1. 最適化済みレジュメと求人票を入力
            2. テキスト直接入力、または過去の変換結果から選択可能
            3. 「マッチング分析を実行」をクリック
            4. スキル比較、一致点・差分の事実ベース分析を取得

            **CV提案コメント抽出**
            1. 英語のCVをテキスト入力またはPDFアップロード
            2. 「抽出実行」をクリック
            3. 匿名提案用の事実ベース5項目（各300文字以内・英語）を取得
            4. 複数CVの一括処理にも対応（---NEXT---で区切り）

            **求人打診メール作成**
            1. 候補者の名前と送信者名を入力
            2. 求人情報（ポジション名、企業名、URL等）を追加
            3. 「メール生成」をクリックでメール文面を自動作成
            4. コピーしてそのままメール送信に利用

            *生成結果は右上のコピーボタンで簡単にコピーできます*
            """,

        # ===== Common UI Elements =====
        "tab_text_input": "テキスト入力",
        "tab_pdf": "PDF読み込み",
        "tab_linkedin": "LinkedIn",
        "sample_btn": "サンプル",
        "sample_help": "サンプルレジュメを挿入",
        "sample_jd_help": "サンプル求人票を挿入",
        "input_resume": "##### 入力：英語レジュメ",
        "paste_resume": "英語のレジュメをペースト",
        "paste_resume_placeholder": "Paste the English resume here...\n\nExample:\nJohn Doe\nSoftware Engineer with 5+ years of experience...",
        "upload_pdf": "##### PDFをアップロード",
        "select_pdf": "PDFファイルを選択",
        "pdf_help": "最大{size}MB、20ページまで",
        "reading_pdf": "PDFを読み込み中...",
        "text_extracted": "✅ テキスト抽出完了（{count}文字）",
        "view_extracted": "抽出されたテキストを確認",
        "linkedin_header": "##### LinkedInプロフィールをコピペ",
        "linkedin_hint": "💡 LinkedInページを開き、プロフィール全体をコピーして貼り付けてください",
        "linkedin_how": "コピー方法",
        "linkedin_instructions": """
                    1. LinkedInでプロフィールページを開く
                    2. `Ctrl+A`（Mac: `Cmd+A`）で全選択
                    3. `Ctrl+C`（Mac: `Cmd+C`）でコピー
                    4. 下のテキストエリアに貼り付け
                    """,
        "paste_linkedin": "LinkedInプロフィールをペースト",
        "linkedin_placeholder": "LinkedInプロフィールページのテキストを貼り付けてください...",
        "linkedin_loaded": "✅ LinkedInテキスト読み込み完了（{count}文字）",
        "char_count_exceeded": "{count} / {max} 文字（超過）",
        "char_count": "{count} / {max} 文字",
        "transform_btn": "変換実行",
        "btn_hint_no_api": "💡 サイドバーでAPIキーを設定してください",
        "btn_hint_no_input": "💡 テキストを入力またはPDFをアップロードしてください",
        "btn_hint_no_both": "💡 両方の入力を完了してください",
        "no_api_key": "❌ APIキーを入力してください",
        "unexpected_error": "❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください",
        "output_placeholder": "左側で入力して「変換実行」をクリックすると、ここに結果が表示されます",
        "formatted_view": "整形表示",
        "formatted_help": "Markdownをフォーマットして表示",
        "copy_btn": "コピー",
        "copied": "✅ クリップボードにコピーしました",
        "editable_output": "出力結果（編集可能）",
        "dl_markdown": "Markdown",
        "dl_text": "テキスト",
        "dl_html": "HTML",
        "dl_html_help": "ブラウザで開いて印刷→PDF保存",
        "share_btn": "共有リンク作成",
        "share_help": "1ヶ月有効の共有リンクを作成",
        "sharing": "共有リンクを作成中...",
        "share_created": "✅ 共有リンクを作成しました（1ヶ月有効）",
        "share_hint": "💡 上のURLをコピーしてクライアントに共有してください",
        "share_failed": "❌ 共有リンクの作成に失敗しました",

        # ===== Anonymization =====
        "anon_label": "匿名化レベル",
        "anon_full": "完全匿名化（個人情報＋企業名＋プロジェクト）",
        "anon_light": "軽度匿名化（個人情報のみ）",
        "anon_none": "匿名化なし",
        "anon_help": "完全：企業名・大学名も業界表現に変換 / 軽度：氏名・連絡先のみ匿名化",
        "anon_full_en": "完全匿名化（企業名も伏せる）",
        "anon_light_en": "軽度匿名化（企業名は表示）",
        "anon_help_en": "完全：企業名を「大手SIer」等に置換 / 軽度：企業名・大学名をそのまま表示（個人情報のみ匿名化）",
        "anon_help_cv": "完全：企業名を「a major IT firm」等に置換 / 軽度：企業名・大学名をそのまま表示",

        # ===== 処理モード =====
        "mode_label": "処理モード",
        "mode_deterministic": "⚡ PIIのみ削除（高速・幻覚ゼロ）",
        "mode_llm_optimize": "🤖 AI最適化（整形・翻訳込み）",
        "mode_help": "PIIのみ削除: 1秒未満・原文そのまま・幻覚なし / AI最適化: 20〜60秒・Markdown整形・日本語化",
        "mode_det_done": "✅ PII削除完了（{time}秒・LLM未使用）",
        "mode_det_residual": "⚠️ 以下のPIIが残存している可能性があります。手動で確認してください:",

        # ===== Feature 1: Resume Optimization =====
        "resume_opt_title": "レジュメ最適化（英語 → 日本語）",
        "resume_opt_desc": "外国人エンジニアの英語レジュメを、日本企業向けの統一フォーマットに変換します",
        "resume_opt_output": "##### 出力：日本企業向けフォーマット",
        "resume_opt_ai": "🤖 AIがレジュメを解析・構造化しています...",
        "resume_opt_done": "✅ 変換完了！（{time}秒）",
        "additional_convert": "##### 追加変換",
        "convert_to_en": "この結果を英語匿名化（English → English）",
        "convert_to_en_help": "生成された日本語レジュメを基に英語匿名化レジュメを生成",
        "generating_en": "英語匿名化レジュメを生成中...",
        "en_done": "✅ 英語匿名化レジュメの生成が完了しました",
        "scroll_hint": "💡 下にスクロールして結果を確認してください",
        "no_original_resume": "❌ 元の英語レジュメが見つかりません。最初から変換し直してください。",
        "generation_error": "❌ 生成エラーが発生しました。しばらく待ってから再試行してください",
        "en_result_header": "##### 英語匿名化レジュメ（追加生成）",

        # ===== Feature 2: Resume Anonymization =====
        "resume_anon_title": "レジュメ匿名化（英語 → 英語）",
        "resume_anon_desc": "英語レジュメを英語のまま匿名化します。海外クライアントへの提出に最適",
        "resume_anon_btn": "匿名化実行",
        "resume_anon_ai": "🤖 AIがレジュメを匿名化しています...",
        "resume_anon_done": "✅ 匿名化完了！（{time}秒）",
        "resume_anon_output": "##### 出力：匿名化された英語レジュメ",
        "convert_to_jp": "この結果を日本語に翻訳（English → Japanese）",
        "convert_to_jp_help": "英語匿名化レジュメを日本語に翻訳",
        "generating_jp": "日本語レジュメを生成中...",
        "jp_result_header": "##### 日本語レジュメ（追加生成）",
        "jp_done": "✅ 日本語レジュメの生成が完了しました",

        # ===== Feature 3: Resume PII Removal =====
        "pii_title": "レジュメ個人情報削除",
        "pii_desc": "レジュメからメール・LinkedIn・電話番号・住所を削除し、氏名をFirst nameのみに変更します",
        "pii_input": "##### 入力：レジュメ",
        "pii_paste": "レジュメをペースト",
        "pii_placeholder": "Paste the resume here...\n\nレジュメのテキストを貼り付けてください...",
        "pii_info": "削除される情報：メールアドレス、LinkedIn、電話番号、住所\n\n氏名はFirst nameのみに変更されます",
        "pii_mode_label": "処理モード",
        "pii_mode_redact_only": "削除のみ（推奨・ハルシネーション最小）",
        "pii_mode_redact_and_format": "削除＋整形（整形で文体変化あり）",
        "pii_mode_help": "「削除のみ」は原文をコピーしてPIIだけを抜きます。精度最優先の運用ではこちらを推奨。「削除＋整形」は削除後にMarkdown整形（セクション並べ替え・箇条書き統一）を追加しますが、整形時に表現が変わる可能性があります。",
        "pii_btn": "個人情報削除実行",
        "pii_output": "##### 出力：個人情報削除済みレジュメ",
        "pii_ai": "🤖 AIがレジュメから個人情報を削除しています...",
        "pii_done": "✅ 個人情報削除完了！（{time}秒）",
        "pii_verifying": "🔍 匿名化の精度を検証中... (試行 {n}/{max})",
        "pii_regenerating": "🔁 検出された問題を修正して再生成中... (試行 {n}/{max})",
        "pii_formatting": "🎨 PII削除済みテキストをMarkdown整形しています...",
        "pii_format_verifying": "🔍 整形後の事実整合性を検証中...",
        "pii_done_verified": "✅ 個人情報削除＋精度検証 合格！（{time}秒 / {iters}回で合格）",
        "pii_max_iter": "⚠️ {iters}回の再生成後も課題が残りました（{time}秒）。検証結果の詳細をご確認ください",
        "pii_verify_details_label": "{icon} 精度検証の詳細（全{iters}回）",
        "pii_iter_label": "試行 {n}",
        "pii_iter_final_label": "最終結果",
        "pii_iter_history_label": "過去の試行履歴（{n}回）を表示",
        "pii_v_leak": "PII残存",
        "pii_v_mismatch": "事実不一致",
        "pii_v_missing": "情報欠落",
        "pii_v_fabricated": "捏造疑い",
        "pii_v_original": "元",
        "pii_v_anonymized": "匿名化後",
        "pii_v_all_clear": "⭕ 問題は検出されませんでした",

        # ===== Feature 4: JD Enhancement (JP→EN) =====
        "jd_jp_en_title": "求人票魅力化（日本語 → 英語）",
        "jd_jp_en_desc": "日本企業の求人票を、外国人エンジニアに魅力的な英語JDに変換します",
        "jd_jp_en_input": "##### 入力：日本語求人票",
        "jd_paste": "日本語の求人票をペースト",
        "jd_paste_placeholder": "求人票をここに貼り付けてください...\n\n例：\n【募集職種】バックエンドエンジニア\n【業務内容】自社サービスの開発...",
        "jd_jp_en_hint": "💡 ビザサポート、リモート可否、給与レンジが記載されていると、より魅力的なJDが生成されます",
        "jd_jp_en_output": "##### 出力：外国人エンジニア向け英語JD",
        "jd_jp_en_ai": "🤖 AIが求人票を解析・魅力化しています...",

        # ===== Feature 5: JD Translation (EN→JP) =====
        "jd_en_jp_title": "求人票翻訳（英語 → 日本語）",
        "jd_en_jp_desc": "海外企業・外資系の英語求人票を、日本人エンジニア向けに最適化された日本語JDに変換します",
        "jd_en_paste": "英語の求人票をペースト",
        "jd_en_paste_placeholder": "Paste the English job description here...",
        "jd_en_jp_hint": "💡 給与がUSD等の外貨の場合、自動で円換算目安も併記されます",
        "jd_en_jp_output": "##### 出力：日本人エンジニア向け求人票",
        "jd_en_jp_ai": "🤖 AIが求人票を翻訳・最適化しています...",
        "jd_upload_pdf": "##### 求人票PDFをアップロード",

        # ===== Feature 6: JD Formatting (JP→JP) =====
        "jd_jp_jp_title": "求人票フォーマット化（日本語 → 日本語）",
        "jd_jp_jp_desc": "日本語の求人票を、統一された見やすいフォーマットの魅力的な日本語JDに変換します",
        "jd_jp_jp_hint": "💡 統一フォーマットに整理され、見やすく魅力的な求人票が生成されます",
        "jd_jp_jp_output": "##### 出力：統一フォーマットの日本語JD",
        "jd_jp_jp_ai": "🤖 AIが求人票を解析・整形しています...",

        # ===== Feature 7: JD Formatting (EN→EN) =====
        "jd_en_en_title": "求人票フォーマット化（English → English）",
        "jd_en_en_desc": "英語の求人票を、外国人エンジニア向けの統一フォーマットに変換します",

        # ===== Feature: JD Anonymization =====
        "jd_anon_title": "求人匿名化",
        "jd_anon_desc": "求人票の企業名・連絡先を匿名化し、候補者への提示用に変換します。入力は日本語・英語どちらでもOK",
        "jd_anon_output": "##### 出力：匿名化された求人票",
        "jd_anon_ai": "🤖 AIが求人票を匿名化しています...",
        "jd_anon_btn": "匿名化実行",
        "jd_anon_input": "##### 入力：求人票（日本語 or 英語）",
        "jd_anon_info": "💡 企業名・連絡先を匿名化し、候補者への提示用に整形します",
        "jd_anon_output_lang_label": "出力言語",
        "jd_anon_output_lang_ja": "日本語で出力",
        "jd_anon_output_lang_en": "English で出力",
        "jd_anon_level_label": "匿名化レベル",
        "jd_anon_level_full": "フル（企業名・住所・連絡先すべて匿名化）",
        "jd_anon_level_light": "ライト（連絡先のみ削除、企業名は残す）",
        "jd_anon_level_none": "なし（匿名化なし、フォーマット整形のみ）",

        # ===== Feature 8: Company Intro =====
        "company_title": "企業紹介文作成（PDF読み取り）",
        "company_desc": "会社紹介資料（PDF）から求職者向けの簡潔な企業紹介文を自動生成します",
        "company_pdf_header": "##### 会社紹介PDFをアップロード",
        "company_text_header": "##### 会社紹介テキストをペースト",
        "company_paste": "会社紹介テキストをペースト",
        "company_placeholder": "会社紹介資料のテキストを貼り付けてください...\n\n例：\n会社名：株式会社〇〇\n設立：2015年\n事業内容：...",
        "company_hint": "💡 会社概要、事業内容、強みなどが含まれたPDFが理想的です",
        "company_btn": "紹介文作成",
        "company_output": "##### 出力：求職者向け企業紹介文",
        "company_ai": "🤖 AIが会社紹介資料を解析しています...",
        "company_done": "✅ 作成完了！（{time}秒）",

        # ===== Feature 9: Matching Analysis =====
        "matching_title": "レジュメ×求人票マッチング分析",
        "matching_desc": "最適化済みレジュメと求人票を入力し、AIがマッチング度を多角的に分析します",
        "matching_resume_header": "##### 入力1: レジュメ",
        "matching_resume_method": "レジュメの入力方法",
        "matching_jd_header": "##### 入力2: 求人票",
        "matching_jd_method": "求人票の入力方法",
        "input_text_pdf": "テキスト/PDF入力",
        "input_from_results": "過去の変換結果から選択",
        "input_from_history": "履歴から選択",
        "optimize_first": "💡 先に「レジュメ最適化」機能を使用してレジュメを最適化してください",
        "manual_input": "または手動入力",
        "select_history": "履歴を選択",
        "view_selected_resume": "選択されたレジュメを確認",
        "view_selected_jd": "選択された求人票を確認",
        "delete_item": "この項目を削除",
        "delete_all_history": "全履歴を削除",
        "no_history_hint": "💡 履歴がありません。マッチング分析を実行すると自動で保存されます。",
        "paste_jd": "求人票をペースト",
        "jd_optimize_first": "💡 先に「求人票魅力化」または「求人票翻訳」機能を使用してください",
        "jd_pdf_header": "##### 求人票PDFをアップロード",
        "both_ready_hint": "💡 両方の入力が完了したら、下のボタンで分析を開始します",
        "matching_btn": "マッチング分析を実行",
        "matching_both_required": "⚠️ レジュメと求人票の両方を入力してください",
        "matching_ai": "🤖 AIがレジュメと求人票を詳細分析しています...",
        "matching_done": "✅ 分析完了！（{time}秒）",
        "matching_result": "### 分析結果",
        "save_reminder": "💾 **データの保存を忘れずに！** スマホやタブを閉じると履歴が消える場合があります。",
        "current_history": "現在の履歴: レジュメ {resume}件、求人票 {jd}件",
        "backup_now": "今すぐバックアップ",

        # Matching - Data Management
        "data_mgmt": "履歴データの管理（エクスポート/インポート）",
        "export_header": "##### エクスポート",
        "export_count": "レジュメ: {resume}件、求人票: {jd}件",
        "export_btn": "すべての履歴をダウンロード",
        "no_history_export": "💡 履歴がありません",
        "import_header": "##### インポート",
        "import_json": "JSONファイルをアップロード",
        "import_json_help": "過去にエクスポートした履歴ファイルを選択",
        "import_btn": "履歴をインポート",

        # Matching - Proposal
        "proposal_header": "#### 候補者提案資料生成",
        "proposal_desc": "マッチング分析から企業向けの簡潔な候補者提案資料を生成します",
        "proposal_ja_btn": "日本語版を生成",
        "proposal_ja_help": "提案資料（日本語）を生成",
        "proposal_en_btn": "English Version",
        "proposal_no_data": "❌ レジュメと求人票の入力情報が見つかりません。先にマッチング分析を実行してください。",
        "proposal_ja_ai": "🤖 候補者提案資料（日本語）を生成中...",
        "proposal_ja_done": "✅ 候補者提案資料（日本語）の生成が完了しました",
        "proposal_en_no_data": "❌ Resume and JD input not found. Please run matching analysis first.",
        "proposal_en_ai": "🤖 Generating candidate proposal (English)...",
        "proposal_en_done": "✅ Candidate proposal (English) generated successfully",
        "proposal_en_error": "❌ Generation error. Please try again later",
        "proposal_result": "#### 生成された候補者提案資料",

        # ===== Feature 10: CV Extract =====
        "cv_title": "CV提案コメント抽出",
        "cv_desc": "CVから提案用の5項目コメント（英語・各300文字以内）を抽出します。複数CVの一括処理にも対応。",
        "cv_mode_label": "入力モード",
        "cv_mode_single": "単体CV入力",
        "cv_mode_batch": "複数CV一括処理",
        "cv_input": "##### 入力：英語CV",
        "cv_paste": "英語のCVをペースト",
        "cv_extract_btn": "抽出実行",
        "cv_output": "##### 出力：提案コメント（英語・各300文字以内）",
        "cv_ai": "🤖 AIがCVからコメントを抽出しています...",
        "cv_done": "✅ 抽出完了！（{time}秒）",
        "cv_length_slider": "文章量（各セクションの目安文字数）",
        "cv_adjust_btn": "文章量を調整",
        "cv_adjusting": "調整中...",
        "cv_adjusted": "✅ 調整完了！",

        # CV Batch
        "cv_batch_hint": "💡 **区切り方法**: `---NEXT---` を各CVの間に入れてください",
        "cv_batch_paste": "複数の英語CVを貼り付け",
        "cv_batch_pdf_header": "##### 複数PDFをアップロード（最大10件）",
        "cv_batch_pdf_label": "PDFファイルを選択（複数選択可）",
        "cv_batch_pdf_help": "各ファイル最大{size}MB、20ページまで。最大10ファイル。",
        "cv_batch_max_error": "❌ 一度にアップロードできるのは最大10件までです",
        "cv_batch_detected": "検出されたCV数",
        "cv_batch_btn": "一括抽出実行",
        "cv_batch_no_cv": "⚠️ CVが検出されませんでした",
        "cv_batch_max_process": "❌ 一度に処理できるのは最大10件までです",
        "cv_batch_progress": "🔄 処理中... ({done}/{total})...",
        "cv_batch_done": "✅ 処理完了！（合計 {time}秒）",
        "cv_batch_result": "抽出結果",
        "cv_batch_success": "✅ 成功",
        "cv_batch_error": "❌ エラー",
        "cv_batch_dl_all": "全件ダウンロード（Markdown）",

        # ===== Feature 11: Email =====
        "email_title": "求人打診メール作成",
        "email_desc": "面談後に候補者へ送る求人打診メールを簡単に作成できます",
        "email_candidate_name": "候補者の名前（First Name）",
        "email_sender": "送信者名",
        "email_saved_data": "##### 保存済みデータから読み込み",
        "email_tab_set": "セットから読み込み",
        "email_tab_individual": "個別求人から選択",
        "email_select_set": "求人セットを選択",
        "email_load_set": "このセットを読み込み",
        "email_no_sets": "保存済みセットはありません。下の求人フォームを入力後「💾 セットとして保存」で作成できます。",
        "email_select_jobs": "メールに含める求人を選択",
        "email_load_jobs": "選択した求人を読み込み",
        "email_no_jobs": "保存済みの個別求人はありません。各求人エントリ内の「💾 この求人を保存」で追加できます。",
        "email_job_header": "##### 求人情報",
        "email_add_job": "＋ 求人を追加",
        "email_remove_job": "－ 最後の求人を削除",
        "email_job_count": "現在の求人数: {count}件（最大10件）",
        "email_job_n": "求人 #{n}",
        "email_auto_read": "**求人を自動読み取り**（PDFまたはURLを入力）",
        "email_job_pdf": "求人PDF",
        "email_job_url": "求人URL",
        "email_job_url_placeholder": "https://... 求人ページのURLを貼り付け",
        "email_read_btn": "読み取り → 自動入力",
        "email_read_done": "✅ 求人 #{n} の情報を自動入力しました",
        "email_read_fail": "解析結果のパースに失敗しました。再度お試しください。",
        "email_need_api": "⚠️ 自動読み取りにはサイドバーでAPIキーの設定が必要です",
        "email_position": "ポジション名",
        "email_company": "企業名",
        "email_overview": "概要 / Overview（任意）",
        "email_keyfocus": "Key Focus（任意）",
        "email_jdnote": "JD備考（任意）",
        "email_recommendation": "おすすめコメント（任意）",
        "email_save_job": "この求人を保存",
        "email_save_set_header": "現在の求人をセットとして保存",
        "email_set_name": "セット名",
        "email_set_name_placeholder": "e.g. Robotics系3社セット",
        "email_save_set_btn": "セットを保存",
        "email_generate_btn": "メール生成",
        "email_lang_label": "メール文面の言語",
        "email_lang_en": "English",
        "email_lang_ja": "日本語",
        "email_output": "##### 生成されたメール",
        "email_dl_text": "テキストファイルDL",
        "email_manage_sets": "セット管理",
        "email_manage_jobs": "個別求人管理",
        "email_delete_set": "すべてのセットを削除",
        "email_delete_jobs": "すべての個別求人を削除",
        "email_no_sets_mgmt": "保存済みセットはありません",
        "email_no_jobs_mgmt": "保存済みの個別求人はありません",

        # ----- Email: Batch Mode -----
        "email_tab_manual": "手動入力モード",
        "email_tab_batch": "一括PDFモード",
        "email_batch_desc": "複数の求人票PDFを一括アップロードし、自動で情報を抽出してメールを生成します",
        "email_batch_upload": "求人票PDFを複数アップロード（最大10件）",
        "email_batch_upload_help": "複数ファイルを選択できます",
        "email_batch_url_label": "または求人URLを入力（1行に1つ）",
        "email_batch_url_placeholder": "https://example.com/job1\nhttps://example.com/job2",
        "email_batch_extract_btn": "一括で情報を抽出",
        "email_batch_extracting": "求人情報を抽出中... ({done}/{total})",
        "email_batch_extract_done": "✅ {count}件の求人情報を抽出しました（{time}秒）",
        "email_batch_extract_error": "❌ 抽出に失敗: {name}",
        "email_batch_no_input": "⚠️ PDFまたはURLを入力してください",
        "email_batch_max_error": "❌ 一度に処理できるのは最大10件までです",
        "email_batch_results": "##### 抽出結果（{count}件）",
        "email_batch_edit_hint": "内容を確認・編集してから「📧 メール生成」を押してください",
        "email_batch_generate_btn": "{count}件分のメールを一括生成",
        "email_batch_clear": "抽出結果をクリア",

        # ===== Feature 12: Batch =====
        "batch_title": "バッチ処理（複数レジュメ一括変換）",
        "batch_desc": "複数の英語レジュメを一括で日本語に変換します。区切り文字で分割してください。",
        "batch_hint": "💡 **区切り方法**: `---NEXT---` を各レジュメの間に入れてください",
        "batch_paste": "複数の英語レジュメを貼り付け",
        "batch_anon_full": "完全匿名化",
        "batch_anon_light": "軽度匿名化",
        "batch_anon_none": "なし",
        "batch_detected": "検出されたレジュメ数",
        "batch_btn": "一括変換実行",
        "batch_no_resume": "⚠️ レジュメが検出されませんでした",
        "batch_max_error": "❌ 一度に処理できるのは最大10件までです",
        "batch_progress": "🔄 処理中... ({done}/{total})",
        "batch_done": "✅ 処理完了！（合計 {time}秒）",
        "batch_result": "処理結果",
        "batch_success": "✅ 成功",
        "batch_error": "❌ エラー",
        "batch_dl_all": "全件ダウンロード（Markdown）",

        # ===== Footer =====
        "footer": "GlobalMatch Assistant",
    },

    "en": {
        # ===== Header =====
        "app_title": "# GlobalMatch Assistant",
        "app_subtitle": "*Streamlining recruitment between international engineers and Japanese companies*",
        "app_name": "GlobalMatch Assistant",
        "app_tagline": "Streamlining recruitment between international engineers and Japanese companies",

        # ===== Sidebar =====
        "settings": "Settings",
        "lang_label": "Language / 言語",
        "api_key_label": "Groq API Key",
        "api_key_placeholder": "gsk_...",
        "api_key_help": "Get a free API key from [Groq Console](https://console.groq.com/keys)",
        "api_key_set": "✅ API key configured (secrets)",
        "gemini_fallback_label": "🔄 Gemini API Key (fallback, optional)",
        "gemini_fallback_placeholder": "Gemini API Key",
        "gemini_fallback_help": "When set, automatically fails over to Gemini 2.5 Flash if Groq hits rate limits. Get a key at [Google AI Studio](https://aistudio.google.com/app/apikey)",
        "gemini_fallback_active": "Gemini fallback active",
        "no_history": "No history found",
        "import_hint": "If you have a backup file, you can import it here",
        "backup_file": "Backup file (JSON)",
        "backup_file_help": "Select a previously exported backup file",
        "restore_btn": "Restore",
        "file_read_error": "File read error: {error}",
        "feature_select": "Features",
        "feature_select_label": "Select mode",
        "feature_select_help": "Select the type of document you want to transform",

        # ===== Feature Names =====
        "feature.resume_optimize": "Resume Optimization (EN→JP)",
        "feature.resume_anonymize": "Resume Anonymization (EN→EN)",
        "feature.resume_pii": "Resume PII Removal",
        "feature.jd_jp_en": "JD Enhancement (JP→EN)",
        "feature.jd_en_jp": "JD Translation (EN→JP)",
        "feature.jd_jp_jp": "JD Formatting (JP→JP)",
        "feature.jd_en_en": "JD Formatting (EN→EN)",
        "feature.jd_anonymize": "JD Anonymization",
        "feature.company_intro": "Company Intro (PDF)",
        "feature.matching": "Resume × JD Matching Analysis",
        "feature.cv_extract": "CV Proposal Comment Extraction",
        "feature.email": "Job Offer Email",
        "feature.batch": "Batch Processing (Multiple Resumes)",

        # ===== Feature Category Labels =====
        "feature_cat_resume": "Resume",
        "feature_cat_jd": "Job Descriptions",
        "feature_cat_analysis": "Analysis & Tools",

        # ===== Onboarding =====
        "onboarding_title": "Welcome!",
        "onboarding_body": "Click the 'Sample' button to load sample data and try out the features right away. Select a feature from the sidebar on the left.",
        "onboarding_dismiss": "Dismiss",

        # ===== Usage Guide =====
        "usage_guide": "How to Use",
        "usage_guide_content": """
            **Resume Optimization (EN→JP)**
            1. Paste an English resume or upload a PDF
            2. Set anonymization options
            3. Click "Transform"

            **Resume Anonymization (EN→EN)**
            1. Paste an English resume or upload a PDF
            2. Select anonymization level
            3. Get the anonymized resume in English

            **Resume PII Removal**
            1. Paste a resume or upload a PDF
            2. Click "Remove PII"
            3. Email, LinkedIn, phone, and address are removed; name is changed to first name only

            **JD Enhancement (JP→EN)**
            1. Paste a Japanese job description
            2. Click "Transform"

            **JD Translation (EN→JP)**
            1. Paste an English job description
            2. Click "Transform"
            3. Optimized for Japanese engineers

            **JD Formatting (JP→JP)**
            1. Paste a Japanese job description
            2. Click "Transform"
            3. Get a well-formatted, attractive Japanese JD

            **JD Formatting (EN→EN)**
            1. Paste an English job description
            2. Click "Transform"
            3. Get a well-formatted, attractive English JD

            **Company Intro (PDF)**
            1. Upload a company introduction PDF
            2. Click "Generate Intro"
            3. Get a concise company introduction for candidates

            **Resume × JD Matching Analysis**
            1. Enter an optimized resume and a job description
            2. Direct text input or select from past results
            3. Click "Run Matching Analysis"
            4. Get fact-based skill comparison and gap analysis

            **CV Proposal Comment Extraction**
            1. Enter an English CV via text or PDF upload
            2. Click "Extract"
            3. Get 5 fact-based proposal items (each ≤300 chars, English)
            4. Batch processing supported (separate with ---NEXT---)

            **Job Offer Email**
            1. Enter candidate name and sender name
            2. Add job information (position, company, URL, etc.)
            3. Click "Generate Email" to create email text
            4. Copy and use directly for sending

            *Use the copy button at the top-right to easily copy results*
            """,

        # ===== Common UI Elements =====
        "tab_text_input": "Text Input",
        "tab_pdf": "PDF Upload",
        "tab_linkedin": "LinkedIn",
        "sample_btn": "Sample",
        "sample_help": "Insert sample resume",
        "sample_jd_help": "Insert sample JD",
        "input_resume": "##### Input: English Resume",
        "paste_resume": "Paste English resume",
        "paste_resume_placeholder": "Paste the English resume here...\n\nExample:\nJohn Doe\nSoftware Engineer with 5+ years of experience...",
        "upload_pdf": "##### Upload PDF",
        "select_pdf": "Select PDF file",
        "pdf_help": "Maximum {size}MB, up to 20 pages",
        "reading_pdf": "Reading PDF...",
        "text_extracted": "✅ Text extracted ({count} characters)",
        "view_extracted": "View extracted text",
        "linkedin_header": "##### Paste LinkedIn Profile",
        "linkedin_hint": "💡 Open your LinkedIn page and copy-paste the entire profile",
        "linkedin_how": "How to Copy",
        "linkedin_instructions": """
                    1. Open your LinkedIn profile page
                    2. `Ctrl+A` (Mac: `Cmd+A`) to select all
                    3. `Ctrl+C` (Mac: `Cmd+C`) to copy
                    4. Paste in the text area below
                    """,
        "paste_linkedin": "Paste LinkedIn profile",
        "linkedin_placeholder": "Paste your LinkedIn profile text here...",
        "linkedin_loaded": "✅ LinkedIn text loaded ({count} characters)",
        "char_count_exceeded": "{count} / {max} characters (exceeded)",
        "char_count": "{count} / {max} characters",
        "transform_btn": "Transform",
        "btn_hint_no_api": "💡 Set your API key in the sidebar",
        "btn_hint_no_input": "💡 Enter text or upload a PDF",
        "btn_hint_no_both": "💡 Complete both inputs to proceed",
        "no_api_key": "❌ Please enter an API key",
        "unexpected_error": "❌ An unexpected error occurred. Please try again later.",
        "output_placeholder": "Enter input on the left and click 'Transform' to see results here",
        "formatted_view": "Formatted View",
        "formatted_help": "Display with Markdown formatting",
        "copy_btn": "Copy",
        "copied": "✅ Copied to clipboard",
        "editable_output": "Output (editable)",
        "dl_markdown": "Markdown",
        "dl_text": "Text",
        "dl_html": "HTML",
        "dl_html_help": "Open in browser and save as PDF via print",
        "share_btn": "Create Share Link",
        "share_help": "Create a shareable link (valid for 1 month)",
        "sharing": "Creating share link...",
        "share_created": "✅ Share link created (valid for 1 month)",
        "share_hint": "💡 Copy the URL above to share with clients",
        "share_failed": "❌ Failed to create share link",

        # ===== Anonymization =====
        "anon_label": "Anonymization Level",
        "anon_full": "Full (personal info + company names + projects)",
        "anon_light": "Light (personal info only)",
        "anon_none": "None",
        "anon_help": "Full: company/university names replaced with industry terms / Light: names & contact only",
        "anon_full_en": "Full anonymization (hide company names)",
        "anon_light_en": "Light anonymization (show company names)",
        "anon_help_en": "Full: company names replaced (e.g., 'Major SIer') / Light: company/university names kept (personal info only anonymized)",
        "anon_help_cv": "Full: company names replaced (e.g., 'a major IT firm') / Light: company/university names kept",

        # ===== Processing Mode =====
        "mode_label": "Processing Mode",
        "mode_deterministic": "⚡ PII removal only (fast, zero hallucination)",
        "mode_llm_optimize": "🤖 AI optimization (formatting + translation)",
        "mode_help": "PII removal only: <1s, verbatim, no hallucination / AI optimization: 20-60s, Markdown formatting, Japanese",
        "mode_det_done": "✅ PII removed in {time}s (no LLM used)",
        "mode_det_residual": "⚠️ The following PII may still remain. Please verify manually:",

        # ===== Feature 1: Resume Optimization =====
        "resume_opt_title": "Resume Optimization (English → Japanese)",
        "resume_opt_desc": "Transform English resumes of international engineers into a standardized Japanese format for Japanese companies",
        "resume_opt_output": "##### Output: Japanese Company Format",
        "resume_opt_ai": "🤖 AI is analyzing and structuring the resume...",
        "resume_opt_done": "✅ Transformation complete! ({time}s)",
        "additional_convert": "##### Additional Conversion",
        "convert_to_en": "Convert to English Anonymized (English → English)",
        "convert_to_en_help": "Generate an English anonymized resume from the original",
        "generating_en": "Generating English anonymized resume...",
        "en_done": "✅ English anonymized resume generated successfully",
        "scroll_hint": "💡 Scroll down to see the result",
        "no_original_resume": "❌ Original English resume not found. Please start over.",
        "generation_error": "❌ Generation error. Please try again later.",
        "en_result_header": "##### English Anonymized Resume (additional)",

        # ===== Feature 2: Resume Anonymization =====
        "resume_anon_title": "Resume Anonymization (English → English)",
        "resume_anon_desc": "Anonymize English resumes while keeping them in English. Ideal for overseas clients.",
        "resume_anon_btn": "Anonymize",
        "resume_anon_ai": "🤖 AI is anonymizing the resume...",
        "resume_anon_done": "✅ Anonymization complete! ({time}s)",
        "resume_anon_output": "##### Output: Anonymized English Resume",
        "convert_to_jp": "Translate to Japanese (English → Japanese)",
        "convert_to_jp_help": "Translate the anonymized English resume to Japanese",
        "generating_jp": "Generating Japanese resume...",
        "jp_result_header": "##### Japanese Resume (additional)",
        "jp_done": "✅ Japanese resume generated successfully",

        # ===== Feature 3: Resume PII Removal =====
        "pii_title": "Resume PII Removal",
        "pii_desc": "Remove email, LinkedIn, phone, and address from resumes. Name is changed to first name only.",
        "pii_input": "##### Input: Resume",
        "pii_paste": "Paste resume",
        "pii_placeholder": "Paste the resume here...",
        "pii_info": "Removed: email, LinkedIn, phone, address\n\nName is changed to first name only",
        "pii_mode_label": "Processing mode",
        "pii_mode_redact_only": "Redact only (recommended, minimal hallucination)",
        "pii_mode_redact_and_format": "Redact + format (wording may change)",
        "pii_mode_help": "'Redact only' copies the original and removes only PII tokens — recommended when accuracy is critical. 'Redact + format' adds a Markdown formatting pass (section reordering, bullet normalization) which may alter wording.",
        "pii_btn": "Remove PII",
        "pii_output": "##### Output: PII-Removed Resume",
        "pii_ai": "🤖 AI is removing personal information from the resume...",
        "pii_done": "✅ PII removal complete! ({time}s)",
        "pii_verifying": "🔍 Verifying anonymization accuracy... (attempt {n}/{max})",
        "pii_regenerating": "🔁 Regenerating to fix detected issues... (attempt {n}/{max})",
        "pii_formatting": "🎨 Applying Markdown formatting to redacted text...",
        "pii_format_verifying": "🔍 Verifying factual consistency after formatting...",
        "pii_done_verified": "✅ PII removal + verification passed! ({time}s / passed on attempt {iters})",
        "pii_max_iter": "⚠️ Issues remain after {iters} regenerations ({time}s). Please review the verification details",
        "pii_verify_details_label": "{icon} Verification details (all {iters} attempts)",
        "pii_iter_label": "Attempt {n}",
        "pii_iter_final_label": "Final result",
        "pii_iter_history_label": "Show previous attempts ({n})",
        "pii_v_leak": "PII leak",
        "pii_v_mismatch": "Fact mismatch",
        "pii_v_missing": "Missing info",
        "pii_v_fabricated": "Possible fabrication",
        "pii_v_original": "original",
        "pii_v_anonymized": "anonymized",
        "pii_v_all_clear": "⭕ No issues detected",

        # ===== Feature 4: JD Enhancement (JP→EN) =====
        "jd_jp_en_title": "JD Enhancement (Japanese → English)",
        "jd_jp_en_desc": "Transform Japanese job descriptions into attractive English JDs for international engineers",
        "jd_jp_en_input": "##### Input: Japanese Job Description",
        "jd_paste": "Paste Japanese job description",
        "jd_paste_placeholder": "Paste the job description here...",
        "jd_jp_en_hint": "💡 Including visa support, remote work options, and salary range will produce a more attractive JD",
        "jd_jp_en_output": "##### Output: English JD for International Engineers",
        "jd_jp_en_ai": "🤖 AI is analyzing and enhancing the job description...",

        # ===== Feature 5: JD Translation (EN→JP) =====
        "jd_en_jp_title": "JD Translation (English → Japanese)",
        "jd_en_jp_desc": "Translate English job descriptions from overseas/foreign companies into optimized Japanese JDs for Japanese engineers",
        "jd_en_paste": "Paste English job description",
        "jd_en_paste_placeholder": "Paste the English job description here...",
        "jd_en_jp_hint": "💡 If salary is in USD or other foreign currency, JPY equivalent will be automatically included",
        "jd_en_jp_output": "##### Output: JD for Japanese Engineers",
        "jd_en_jp_ai": "🤖 AI is translating and optimizing the job description...",
        "jd_upload_pdf": "##### Upload Job Description PDF",

        # ===== Feature 6: JD Formatting (JP→JP) =====
        "jd_jp_jp_title": "JD Formatting (Japanese → Japanese)",
        "jd_jp_jp_desc": "Transform Japanese job descriptions into a standardized, attractive format",
        "jd_jp_jp_hint": "💡 The output will follow a standardized, easy-to-read format",
        "jd_jp_jp_output": "##### Output: Formatted Japanese JD",
        "jd_jp_jp_ai": "🤖 AI is analyzing and formatting the job description...",

        # ===== Feature 7: JD Formatting (EN→EN) =====
        "jd_en_en_title": "JD Formatting (English → English)",
        "jd_en_en_desc": "Transform English job descriptions into an attractive, well-structured format for international engineers",

        # ===== Feature: JD Anonymization =====
        "jd_anon_title": "JD Anonymization",
        "jd_anon_desc": "Anonymize company names and contact info in job descriptions for candidate presentation. Accepts both Japanese and English input",
        "jd_anon_output": "##### Output: Anonymized Job Description",
        "jd_anon_ai": "🤖 AI is anonymizing the job description...",
        "jd_anon_btn": "Anonymize",
        "jd_anon_input": "##### Input: Job Description (Japanese or English)",
        "jd_anon_info": "💡 Anonymizes company names and contact info, formatting the JD for candidate presentation",
        "jd_anon_output_lang_label": "Output Language",
        "jd_anon_output_lang_ja": "Output in Japanese",
        "jd_anon_output_lang_en": "Output in English",
        "jd_anon_level_label": "Anonymization Level",
        "jd_anon_level_full": "Full (anonymize company, address, and all contacts)",
        "jd_anon_level_light": "Light (remove contacts only, keep company name)",
        "jd_anon_level_none": "None (no anonymization, format only)",

        # ===== Feature 8: Company Intro =====
        "company_title": "Company Intro Generator (PDF)",
        "company_desc": "Auto-generate a concise company introduction for candidates from a company PDF",
        "company_pdf_header": "##### Upload Company Introduction PDF",
        "company_text_header": "##### Paste Company Introduction Text",
        "company_paste": "Paste company introduction text",
        "company_placeholder": "Paste the company introduction text here...\n\nExample:\nCompany: XYZ Corp.\nFounded: 2015\nBusiness: ...",
        "company_hint": "💡 PDFs containing company overview, business details, and strengths work best",
        "company_btn": "Generate Intro",
        "company_output": "##### Output: Company Introduction for Candidates",
        "company_ai": "🤖 AI is analyzing the company materials...",
        "company_done": "✅ Generation complete! ({time}s)",

        # ===== Feature 9: Matching Analysis =====
        "matching_title": "Resume × JD Matching Analysis",
        "matching_desc": "Input an optimized resume and job description for AI-powered multi-angle matching analysis",
        "matching_resume_header": "##### Input 1: Resume",
        "matching_resume_method": "Resume input method",
        "matching_jd_header": "##### Input 2: Job Description",
        "matching_jd_method": "JD input method",
        "input_text_pdf": "Text/PDF Input",
        "input_from_results": "Select from past results",
        "input_from_history": "Select from history",
        "optimize_first": "💡 Please use the 'Resume Optimization' feature first to optimize the resume",
        "manual_input": "Or enter manually",
        "select_history": "Select from history",
        "view_selected_resume": "View selected resume",
        "view_selected_jd": "View selected JD",
        "delete_item": "Delete this item",
        "delete_all_history": "Delete all history",
        "no_history_hint": "💡 No history. Run matching analysis to auto-save.",
        "paste_jd": "Paste job description",
        "jd_optimize_first": "💡 Please use 'JD Enhancement' or 'JD Translation' first",
        "jd_pdf_header": "##### Upload JD PDF",
        "both_ready_hint": "💡 Once both inputs are ready, click the button below to start analysis",
        "matching_btn": "Run Matching Analysis",
        "matching_both_required": "⚠️ Please enter both a resume and a job description",
        "matching_ai": "🤖 AI is performing detailed analysis of resume and JD...",
        "matching_done": "✅ Analysis complete! ({time}s)",
        "matching_result": "### Analysis Results",
        "save_reminder": "💾 **Don't forget to save!** History may be lost if you close the browser or tab.",
        "current_history": "Current history: {resume} resume(s), {jd} JD(s)",
        "backup_now": "Back Up Now",

        # Matching - Data Management
        "data_mgmt": "History Data Management (Export/Import)",
        "export_header": "##### Export",
        "export_count": "Resumes: {resume}, JDs: {jd}",
        "export_btn": "Download All History",
        "no_history_export": "💡 No history available",
        "import_header": "##### Import",
        "import_json": "Upload JSON file",
        "import_json_help": "Select a previously exported history file",
        "import_btn": "Import History",

        # Matching - Proposal
        "proposal_header": "#### Candidate Proposal Generation",
        "proposal_desc": "Generate a concise candidate proposal for client companies from matching analysis",
        "proposal_ja_btn": "Generate Japanese Version",
        "proposal_ja_help": "Generate proposal (Japanese)",
        "proposal_en_btn": "English Version",
        "proposal_no_data": "❌ Resume and JD input not found. Please run matching analysis first.",
        "proposal_ja_ai": "🤖 Generating candidate proposal (Japanese)...",
        "proposal_ja_done": "✅ Candidate proposal (Japanese) generated successfully",
        "proposal_en_no_data": "❌ Resume and JD input not found. Please run matching analysis first.",
        "proposal_en_ai": "🤖 Generating candidate proposal (English)...",
        "proposal_en_done": "✅ Candidate proposal (English) generated successfully",
        "proposal_en_error": "❌ Generation error. Please try again later",
        "proposal_result": "#### Generated Candidate Proposal",

        # ===== Feature 10: CV Extract =====
        "cv_title": "CV Proposal Comment Extraction",
        "cv_desc": "Extract 5 proposal items (English, ≤300 chars each) from CVs. Supports batch processing.",
        "cv_mode_label": "Input Mode",
        "cv_mode_single": "Single CV",
        "cv_mode_batch": "Batch CV Processing",
        "cv_input": "##### Input: English CV",
        "cv_paste": "Paste English CV",
        "cv_extract_btn": "Extract",
        "cv_output": "##### Output: Proposal Comments (English, ≤300 chars each)",
        "cv_ai": "🤖 AI is extracting comments from the CV...",
        "cv_done": "✅ Extraction complete! ({time}s)",
        "cv_length_slider": "Text Length (target chars per section)",
        "cv_adjust_btn": "Adjust Length",
        "cv_adjusting": "Adjusting...",
        "cv_adjusted": "✅ Adjustment complete!",

        # CV Batch
        "cv_batch_hint": "💡 **Separator**: Insert `---NEXT---` between each CV",
        "cv_batch_paste": "Paste multiple English CVs",
        "cv_batch_pdf_header": "##### Upload Multiple PDFs (max 10)",
        "cv_batch_pdf_label": "Select PDF files (multiple)",
        "cv_batch_pdf_help": "Max {size}MB per file, up to 20 pages. Max 10 files.",
        "cv_batch_max_error": "❌ Maximum 10 files can be uploaded at once",
        "cv_batch_detected": "CVs Detected",
        "cv_batch_btn": "Batch Extract",
        "cv_batch_no_cv": "⚠️ No CVs detected",
        "cv_batch_max_process": "❌ Maximum 10 CVs can be processed at once",
        "cv_batch_progress": "🔄 Processing... ({done}/{total})...",
        "cv_batch_done": "✅ Processing complete! (Total {time}s)",
        "cv_batch_result": "Extraction Results",
        "cv_batch_success": "✅ Success",
        "cv_batch_error": "❌ Error",
        "cv_batch_dl_all": "Download All (Markdown)",

        # ===== Feature 11: Email =====
        "email_title": "Job Offer Email Generator",
        "email_desc": "Easily create job offer emails to send candidates after interviews",
        "email_candidate_name": "Candidate Name (First Name)",
        "email_sender": "Sender Name",
        "email_saved_data": "##### Load from Saved Data",
        "email_tab_set": "Load from Set",
        "email_tab_individual": "Select Individual Jobs",
        "email_select_set": "Select job set",
        "email_load_set": "Load This Set",
        "email_no_sets": "No saved sets. Fill in the job form below and click '💾 Save as Set' to create one.",
        "email_select_jobs": "Select jobs to include in email",
        "email_load_jobs": "Load Selected Jobs",
        "email_no_jobs": "No saved jobs. Use '💾 Save This Job' in each job entry to add them.",
        "email_job_header": "##### Job Information",
        "email_add_job": "＋ Add Job",
        "email_remove_job": "－ Remove Last Job",
        "email_job_count": "Current jobs: {count} (max 10)",
        "email_job_n": "Job #{n}",
        "email_auto_read": "**Auto-read job** (enter PDF or URL)",
        "email_job_pdf": "Job PDF",
        "email_job_url": "Job URL",
        "email_job_url_placeholder": "https://... Paste job page URL",
        "email_read_btn": "Read → Auto-fill",
        "email_read_done": "✅ Job #{n} auto-filled",
        "email_read_fail": "Failed to parse results. Please try again.",
        "email_need_api": "⚠️ API key is required for auto-reading. Set it in the sidebar.",
        "email_position": "Position Name",
        "email_company": "Company Name",
        "email_overview": "Overview (optional)",
        "email_keyfocus": "Key Focus (optional)",
        "email_jdnote": "JD Notes (optional)",
        "email_recommendation": "Recommendation Comment (optional)",
        "email_save_job": "Save This Job",
        "email_save_set_header": "Save Current Jobs as Set",
        "email_set_name": "Set Name",
        "email_set_name_placeholder": "e.g. Robotics 3-company set",
        "email_save_set_btn": "Save Set",
        "email_generate_btn": "Generate Email",
        "email_lang_label": "Email Language",
        "email_lang_en": "English",
        "email_lang_ja": "日本語",
        "email_output": "##### Generated Email",
        "email_dl_text": "Download as Text",
        "email_manage_sets": "Set Management",
        "email_manage_jobs": "Job Management",
        "email_delete_set": "Delete All Sets",
        "email_delete_jobs": "Delete All Jobs",
        "email_no_sets_mgmt": "No saved sets",
        "email_no_jobs_mgmt": "No saved jobs",

        # ----- Email: Batch Mode -----
        "email_tab_manual": "Manual Input Mode",
        "email_tab_batch": "Batch PDF Mode",
        "email_batch_desc": "Upload multiple job posting PDFs at once to auto-extract info and generate emails",
        "email_batch_upload": "Upload job posting PDFs (max 10)",
        "email_batch_upload_help": "You can select multiple files",
        "email_batch_url_label": "Or enter job URLs (one per line)",
        "email_batch_url_placeholder": "https://example.com/job1\nhttps://example.com/job2",
        "email_batch_extract_btn": "Batch Extract Info",
        "email_batch_extracting": "Extracting job info... ({done}/{total})",
        "email_batch_extract_done": "✅ Extracted {count} job(s) ({time}s)",
        "email_batch_extract_error": "❌ Extraction failed: {name}",
        "email_batch_no_input": "⚠️ Please upload PDFs or enter URLs",
        "email_batch_max_error": "❌ Maximum 10 items can be processed at once",
        "email_batch_results": "##### Extraction Results ({count} jobs)",
        "email_batch_edit_hint": "Review and edit before clicking 'Generate Email'",
        "email_batch_generate_btn": "Generate Emails for {count} Job(s)",
        "email_batch_clear": "Clear Extraction Results",

        # ===== Feature 12: Batch =====
        "batch_title": "Batch Processing (Multiple Resumes)",
        "batch_desc": "Bulk-convert multiple English resumes to Japanese. Separate with delimiter.",
        "batch_hint": "💡 **Separator**: Insert `---NEXT---` between each resume",
        "batch_paste": "Paste multiple English resumes",
        "batch_anon_full": "Full anonymization",
        "batch_anon_light": "Light anonymization",
        "batch_anon_none": "None",
        "batch_detected": "Resumes Detected",
        "batch_btn": "Batch Convert",
        "batch_no_resume": "⚠️ No resumes detected",
        "batch_max_error": "❌ Maximum 10 resumes can be processed at once",
        "batch_progress": "🔄 Processing... ({done}/{total})",
        "batch_done": "✅ Processing complete! (Total {time}s)",
        "batch_result": "Processing Results",
        "batch_success": "✅ Success",
        "batch_error": "❌ Error",
        "batch_dl_all": "Download All (Markdown)",

        # ===== Footer =====
        "footer": "GlobalMatch Assistant v2.0 | Powered by Groq (Llama 3.3 70B)",
    },
}

# Feature key list (internal keys used for radio selection)
FEATURE_KEYS = [
    "resume_optimize",
    "resume_anonymize",
    "resume_pii",
    "jd_jp_en",
    "jd_en_jp",
    "jd_jp_jp",
    "jd_en_en",
    "jd_anonymize",
    "company_intro",
    "matching",
    "cv_extract",
    "email",
    "batch",
]
