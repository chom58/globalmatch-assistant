"""GlobalMatch Assistant - プロンプト定義"""


def get_resume_optimization_prompt(resume_text: str, anonymize: str) -> str:
    """レジュメ最適化用のプロンプトを生成"""

    if anonymize == "full":
        anonymize_instruction = """
【完全匿名化処理 - 必須】
以下の情報を必ず匿名化してください：

■ 個人情報 → イニシャル表記
- 氏名 → イニシャルに変換（例：田中太郎 → T.T.、John Smith → J.S.）
- メールアドレス → 記載しない
- 電話番号 → 記載しない
- 住所 → 都道府県名のみ（例：「東京都」）
- LinkedIn、GitHub、Portfolio、SNSのURL → 記載しない

■ 企業情報 → 業界・規模で表現
- 具体的な企業名 → 業界+規模に変換（例：「Google」→「米国大手テック企業」「楽天」→「国内大手IT企業」）
- スタートアップ → 「〇〇領域スタートアップ」
- 受託/SIer → 「大手SIer」「中堅SI企業」など
- 外資系 → 「外資系〇〇企業」

■ プロジェクト情報 → 汎用化
- 具体的なプロダクト名 → 「大規模ECサイト」「FinTechアプリ」など汎用表現に
- クライアント名 → 「大手小売業クライアント」など業界で表現
- 特定可能なプロジェクトコード → 削除

■ その他
- 大学名 → 「国内有名私立大学」「海外工科大学」など
- 資格の発行番号 → 削除（資格名は残す）
"""
    elif anonymize == "light":
        anonymize_instruction = """
【軽度匿名化処理 - 必須】
以下の個人情報のみ匿名化してください（企業名は残す）：

- 氏名 → イニシャルに変換（例：田中太郎 → T.T.、John Smith → J.S.）
- メールアドレス → 記載しない
- 電話番号 → 記載しない
- 詳細住所 → 都道府県名まで残す
- LinkedIn、GitHub、SNSのURL → 記載しない

※ 企業名、大学名、プロジェクト名はそのまま残してください。
"""
    else:
        anonymize_instruction = "【匿名化処理】不要です。すべての情報をそのまま残してください。"

    # 基本情報フォーマットの準備
    if anonymize in ["full", "light"]:
        basic_info_format = "- 氏名：（イニシャルで表記。例：T.Y.）\n- 連絡先：[非公開]\n- 所在地：（都道府県のみ）"
    else:
        basic_info_format = "- 氏名：\n- 連絡先：\n- 所在地："

    return f"""あなたはIT・専門職領域に強いハイクラス人材エージェントです。
候補者の英語レジュメを読み込み、クライアント企業への推薦用に「匿名化」しつつ、その「市場価値を最大化」した紹介資料を作成してください。
日本企業の採用担当者向けに最適化された日本語ドキュメントに変換してください。

{anonymize_instruction}

【出力フォーマット - 厳守】
以下の「日本企業向け標準フォーマット」に必ず従って出力してください。
元のレジュメのフォーマットに関わらず、この構造で統一してください。

---

## 1. 基本情報
{basic_info_format}

## 2. 候補者スナップショット
| 項目 | 内容 |
|------|------|
| 専門領域 | （例：LLM / NLP / RAGパイプライン、バックエンド / マイクロサービス等。レジュメの経歴から判断） |
| エンジニア歴 | （総年数。AI/ML経験があれば「12年（うちAI/ML 7年）」のように内訳も記載） |
| 現在のレベル | （ジュニア / ミドル / シニア / リード / マネージャー。直近の役職・経験年数から推定） |
| 直近の注力技術 | （直近1-2年の職歴で使用している主要技術を3-5個） |
| 所在地 | （レジュメ記載の居住国・都市。記載なしの場合は「記載なし」） |

## 3. Professional Summary（経歴サマリ）
*（3〜5行で、候補者の最大の「売り」を記載。経験年数×技術×強みの掛け合わせで市場価値を表現する。ただし事実に基づくこと。「優秀」「卓越」等の主観的形容は使わず、具体的な数字・技術名・実績で説得力を持たせる）*
- 総経験年数と主な役職
- 主要な技術領域・業界
- レジュメに明記されている定量的な実績（あれば）
- 他の候補者と差別化できる経験の組み合わせ（例：「MLエンジニアリング×大規模プロダクション×マネジメント」）

**キャリアパス**: （例：Backend Engineer → ML Engineer → Senior ML Engineer → AI Platform Lead）
*（職歴から抽出した1行のキャリア遷移。事実のみ記載）*

## 4. 技術スタック・習熟度
| カテゴリ | スキル | 経験年数 | 習熟度 |
|---------|--------|----------|--------|
| プログラミング言語 | | | |
| AI/MLフレームワーク | （PyTorch, TensorFlow, JAX, Hugging Face等） | | |
| モデル種別・専門領域 | （LLM, CV, NLP, RL, 推薦, RAG等） | | |
| MLOps/推論基盤 | （MLflow, Kubeflow, SageMaker, TensorRT等） | | |
| データ基盤 | （Spark, Airflow, BigQuery等） | | |
| フレームワーク（Web等） | | | |
| データベース | | | |
| インフラ/クラウド | | | |
| ツール/その他 | | | |

*習熟度: Expert（専門家レベル）/ Advanced（上級）/ Intermediate（中級）/ Beginner（初級）*
*※ 該当カテゴリに情報がない場合はその行を省略*

## 5. 語学・ビザ
- **日本語レベル**: （JLPTレベルだけでなく、実務でどう活用しているかを文脈から読み取って補足。例：「JLPT N2。日本語での仕様書作成、クライアントとの要件定義MTGに参加」「JLPT N3。日常会話レベル、技術文書は英語メイン」。日本滞在歴があれば記載）
- **英語レベル**: （同様に実務活用を補足。例：「ネイティブ」「ビジネスレベル。海外ベンダーとの技術折衝、英語での技術プレゼン経験あり」）
- **その他の言語**: （該当があれば記載）
- **ビザステータス**: （記載があれば、なければ「要確認」）

## 6. 代表プロジェクト
*（職務経歴の中から最もインパクトのあったプロジェクトを1つ選び、以下の構造で記載）*
- **課題**: （どんな問題・ニーズがあったか）
- **解決策**: （候補者が何を設計・実装したか）
- **技術スタック**: （使用した主要技術）
- **成果**: （定量的な結果。数値があれば必ず含める）
- **チーム体制**: （チーム規模と候補者の役割）

## 7. 職務経歴
*（新しい順に記載）*

### 【会社名】（期間：YYYY年MM月 〜 YYYY年MM月）
**役職/ポジション**

**プロジェクト概要:**
- プロダクト/サービスの種類・規模（例：月間100万ユーザーのECプラットフォーム）

**担当業務・成果:**
- （具体的な成果を数値付きで記載：ユーザー数増加、パフォーマンス改善率、コスト削減額など）
- （チーム規模、技術的チャレンジ、ビジネスインパクトを含める）

## 8. リーダーシップ・ソフトスキル
*（該当する経験がある場合のみ記載）*
- メンタリング・チーム管理経験
- クロスファンクショナルチームでの協業
- 技術プレゼンテーション・登壇
- 採用面接への参加

## 9. 研究実績・学術活動
*（該当する実績がある場合のみ記載）*
- 論文発表（カンファレンス名・ジャーナル名、論文タイトル、発表年）
- Kaggle・MLコンペティション実績（ランキング、メダル）
- 特許（出願・取得）

## 10. オープンソース・副業プロジェクト
*（該当する活動がある場合のみ記載）*
- OSS貢献（プロジェクト名、貢献内容、影響度）
- 個人プロジェクト（概要、技術スタック、ユーザー数など）
- 技術コミュニティ活動（登壇、記事執筆、コミュニティ運営など）

## 11. 受賞歴・表彰
*（該当する実績がある場合のみ記載）*
- 社内表彰、ハッカソン受賞、競技プログラミング、特許など

## 12. 継続的学習
*（最近の学習活動がある場合のみ記載）*
- 最近取得した資格・修了したコース
- カンファレンス参加・登壇
- 技術ブログ・記事執筆

---

【入力レジュメ】
{resume_text}

---

【重要な抽出指示】
上記のレジュメを解析し、指定フォーマットで日本語に変換してください。
以下の点に特に注意してください：

1. **成果には必ず数値を含める**: ユーザー数、パフォーマンス改善率、コスト削減額、チーム規模など
2. **AI/ML固有の成果指標も抽出**: モデル精度改善（accuracy, F1スコア等）、推論レイテンシ（p99 latency等）、学習データ規模（トークン数、データ量）、学習コスト削減（GPU時間等）、プロダクション規模（日次リクエスト数等）
3. **技術スキルには経験年数・習熟度を併記**: 職歴の時期から推定して記載。特にAI/ML関連技術は細かく分類
4. **リーダーシップ経験を見逃さない**: メンター、チームリード、採用関与など
5. **プロジェクトの規模感を記載**: ユーザー数、売上、予算、チーム規模など
6. **代表プロジェクトの選定**: 職歴の中から最もインパクトのあるプロジェクトを1つ選び、課題→解決策→技術→成果→体制の構造で深掘り
7. **研究実績・論文を見逃さない**: 学会発表、ジャーナル掲載、Kaggle実績、特許など
8. **OSS貢献・副業があれば必ず記載**: GitHub、個人プロジェクト、登壇、記事執筆など
9. **受賞歴・表彰があれば記載**: 社内賞、ハッカソン、競技プログラミングなど
10. **最近の学習活動を記載**: 資格取得、コース修了、カンファレンス参加など
11. **キャリアパスの抽出**: 職歴全体を俯瞰し、キャリアの遷移を1行で表現（例：Backend → ML → AI Platform Lead）
12. **語学力の解釈**: 単なる資格名（JLPT N3, TOEIC等）だけでなく、実務でどう活用しているか（仕様書作成、海外ベンダー調整、クライアントとの折衝等）を文脈から読み取って補足する
13. **最新トレンドの反映**: AIツール（GitHub Copilot, ChatGPT API等）の活用やモダンな開発手法（Agile, Scrum, DevOps, CI/CD, IaC等）の経験があれば必ず強調する
14. **実績の抽象化と具体化のバランス**: 守秘義務に触れない範囲で、数字や技術名を用いて「何ができるか」を具体化する。抽象的すぎる表現（「様々なプロジェクトに参画」）は避け、規模・技術・成果を含めた具体的な記述に変換する

**重要**: レジュメに情報が全くない場合のみ「記載なし」とし、少しでも関連する記述があれば必ず抽出して記載してください。
**重要**: 該当するセクション（研究実績、OSS、受賞歴など）に情報がない場合は、そのセクション自体を省略してください。
"""


def get_english_anonymization_prompt(resume_text: str, anonymize: str) -> str:
    """英文レジュメを英文のまま匿名化するプロンプトを生成"""

    if anonymize == "full":
        anonymize_instruction = """
【FULL ANONYMIZATION - REQUIRED】
You MUST anonymize the following information:

■ Personal Information → Use Initials
- Full name → Convert to initials (e.g., John Smith → J.S., Maria Garcia → M.G.)
- Email address → Do not include
- Phone number → Do not include
- Address → State/Country only (e.g., "California, USA" or "Tokyo, Japan")
- LinkedIn, GitHub, Portfolio, Social media URLs → Do not include

■ Company Information → Use Industry/Size Description
- Specific company names → Convert to industry + size (e.g., "Google" → "Major US Tech Company", "Toyota" → "Leading Japanese Automotive Corporation")
- Startups → "[Industry] Startup" (e.g., "FinTech Startup", "AI/ML Startup")
- Consulting firms → "Global Consulting Firm", "Big 4 Consulting"
- Specific product names → Generic descriptions (e.g., "Gmail" → "Large-scale Email Platform")

■ Project Information → Generalize
- Specific product names → "Large-scale E-commerce Platform", "Mobile Banking App", etc.
- Client names → "Major Retail Client", "Fortune 500 Financial Services Company", etc.
- Project codes or internal names → Remove

■ Education
- University names → "Top US University", "Prestigious Engineering School", "Ivy League University", etc.
- Certification IDs/numbers → Remove (keep certification names)
"""
    elif anonymize == "light":
        anonymize_instruction = """
【LIGHT ANONYMIZATION - REQUIRED】
Only anonymize personal contact information (keep company names):

- Full name → Convert to initials (e.g., John Smith → J.S.)
- Email address → Do not include
- Phone number → Do not include
- Detailed address → Keep only city/state level
- LinkedIn, GitHub, Social media URLs → Do not include

※ Keep company names, university names, and project names as-is.
"""
    else:
        anonymize_instruction = "【NO ANONYMIZATION】Keep all information as-is."

    # 基本情報フォーマットの準備
    if anonymize in ["full", "light"]:
        basic_info_format_en = "- Name: (Initials only, e.g., J.S.)\n- Contact: [Confidential]\n- Location: (State/Country only)"
    else:
        basic_info_format_en = "- Name:\n- Contact:\n- Location:"

    return f"""You are a high-end talent agent specializing in IT and technical professionals.
Read the candidate's resume and create a professional introduction document that anonymizes personal information while maximizing the candidate's market value.
Keep the output in English and maintain a professional format.

{anonymize_instruction}

【OUTPUT FORMAT - STRICTLY FOLLOW】
Maintain the resume in English with this standardized structure:

---

## 1. Basic Information
{basic_info_format_en}

## 2. Candidate Snapshot
| Item | Details |
|------|---------|
| Specialization | (e.g., LLM / NLP / RAG Pipelines, Backend / Microservices. Determine from resume experience) |
| Engineering Experience | (Total years. If AI/ML experience exists, break down: e.g., "12 years (7 years in AI/ML)") |
| Current Level | (Junior / Mid / Senior / Lead / Manager. Estimate from most recent role and years of experience) |
| Recent Focus Technologies | (3-5 key technologies used in the last 1-2 years of work history) |
| Location | (Country/city from resume. "Not specified" if not mentioned) |

## 3. Professional Summary
*(3-5 lines highlighting the candidate's key selling points: years of experience × technology × strengths. Express market value through the combination of these factors. Use specific numbers, technology names, and achievements for persuasiveness — but no subjective adjectives like "seasoned", "exceptional", or "passionate". No characterizing skills as "rare" or "unique".)*
- Total years of experience and primary job titles held
- Key technical domains and industries worked in
- Notable quantified achievements (only if explicitly stated in the resume)
- Differentiating combination of experiences (e.g., "ML engineering × large-scale production × team management")

**Career Path**: (e.g., Backend Engineer → ML Engineer → Senior ML Engineer → AI Platform Lead)
*(One-line career progression extracted from work history — facts only)*

## 4. Technical Skills & Proficiency
| Category | Skills | Years of Experience | Proficiency Level | Last Used |
|----------|--------|---------------------|-------------------|-----------|
| Programming Languages | | | | |
| AI/ML Frameworks | (PyTorch, TensorFlow, JAX, Hugging Face, etc.) | | | |
| Model Types & Domains | (LLM, CV, NLP, RL, Recommendation, RAG, etc.) | | | |
| MLOps & Inference | (MLflow, Kubeflow, SageMaker, TensorRT, etc.) | | | |
| Data Infrastructure | (Spark, Airflow, BigQuery, etc.) | | | |
| Frameworks (Web, etc.) | | | | |
| Databases | | | | |
| Cloud & Infrastructure | | | | |
| Tools & Others | | | | |

*Proficiency Levels: Expert / Advanced / Intermediate / Beginner*
*Last Used: "Currently using", "2024", "2022", etc. — estimate from work history dates*
*Omit categories with no relevant information*

## 5. Languages & Visa
- **Japanese Level**: (Beyond just the JLPT level — interpret from context how the language is used in practice. E.g., "JLPT N2. Writes technical specifications in Japanese, participates in client requirements meetings in Japanese" or "JLPT N3. Conversational level, primarily uses English for technical work". Include Japan residency history if available)
- **English Level**: (Similarly interpret practical usage. E.g., "Native" or "Business level. Experience in technical negotiations with overseas vendors, technical presentations in English")
- **Other Languages**: (If applicable)
- **Visa Status**: (If mentioned, otherwise "To be confirmed")

## 6. Highlight Project
*(Select the single most impactful project from work history and describe in this structure)*
- **Challenge**: (What problem or need existed)
- **Solution**: (What the candidate designed and implemented)
- **Tech Stack**: (Key technologies used)
- **Results**: (Quantitative outcomes — include numbers where available)
- **Team**: (Team size and the candidate's role)

## 7. Work Experience
*(Most recent first)*

### [Company Description] (Period: MMM YYYY – MMM YYYY)
**Position/Role**

**Project Context:**
- Product/service type and scale (e.g., E-commerce platform with 1M+ monthly users)

**Key Responsibilities & Achievements:**
- (Specific achievements with metrics: user growth, performance improvements, cost savings, etc.)
- (Team size, technical challenges, business impact)

## 8. Leadership & Soft Skills
*(Include only if applicable)*
- Mentoring & team management experience
- Cross-functional collaboration
- Technical presentations & speaking
- Interview participation

## 9. Research & Academic Activities
*(Include only if applicable)*
- Published papers (conference/journal name, paper title, year)
- Kaggle / ML competition results (ranking, medals)
- Patents (filed or granted)

## 10. Open Source & Side Projects
*(Include only if applicable)*
- OSS contributions (project name, contribution type, impact metrics)
- Personal projects (overview, tech stack, user metrics)
- Technical community involvement (speaking, writing, organizing)

## 11. Awards & Recognition
*(Include only if applicable)*
- Company awards, hackathon wins, competitive programming, patents, etc.

## 12. Continuous Learning
*(Include only if applicable)*
- Recent certifications or completed courses
- Conference attendance or speaking
- Technical blog posts or articles

## 13. Education
- **Degree** - [University Description], Year

## 14. Certifications
- Certification names (without ID numbers)

---

【INPUT RESUME】
{resume_text}

---

【IMPORTANT EXTRACTION INSTRUCTIONS】
Parse the above resume and output in the specified format in English.
Pay special attention to the following:

1. **Always include metrics in achievements**: User numbers, performance improvement %, cost savings, team size, etc.
2. **Extract AI/ML-specific metrics**: Model accuracy improvements (accuracy, F1 score, etc.), inference latency (p99 latency, etc.), training data scale (token count, data volume), training cost reduction (GPU hours, etc.), production scale (daily request volume, etc.)
3. **Specify experience years, proficiency, and last-used date for technical skills**: Estimate from work history dates. Classify AI/ML technologies in detail
4. **Don't miss leadership experience**: Mentoring, team lead, hiring involvement, etc.
5. **Include project scale information**: User count, revenue, budget, team size, etc.
6. **Select highlight project**: Choose the single most impactful project from work history and describe using the Challenge → Solution → Tech → Results → Team structure
7. **Don't miss research & publications**: Conference papers, journal publications, Kaggle results, patents
8. **Extract OSS contributions & side projects**: GitHub, personal projects, speaking, writing, etc.
9. **Include awards & recognition**: Company awards, hackathons, competitive programming, etc.
10. **Capture recent learning activities**: Certifications, courses, conference attendance, etc.
11. **Extract career path**: Summarize the overall career progression in one line (e.g., Backend → ML → AI Platform Lead)
12. **Interpret language proficiency**: Go beyond just listing certification names (JLPT N3, TOEIC, etc.). Read from context how the language is actually used in practice (e.g., writing specifications, coordinating with overseas vendors, client-facing meetings)
13. **Highlight modern trends**: If the candidate uses AI tools (GitHub Copilot, ChatGPT API, etc.) or modern development practices (Agile, Scrum, DevOps, CI/CD, IaC, etc.), always emphasize these
14. **Balance abstraction and specificity**: Use numbers and technology names to concretize "what they can do" within the bounds of confidentiality. Avoid overly abstract expressions (e.g., "participated in various projects") — instead, include scale, technology, and outcomes

**IMPORTANT**: Only use "Not specified" when there is absolutely NO related information in the resume. If there's any relevant mention, extract and include it.
**IMPORTANT**: Omit entire sections (Research, OSS, Awards, etc.) if there's no information, rather than listing them as empty.
"""


def get_resume_pii_removal_prompt(resume_text: str) -> str:
    """レジュメから個人情報を削除し、高品質なMarkdown形式に再構成するプロンプトを生成"""

    return f"""You are a professional English resume editing specialist for technical and managerial roles.
Your task is to convert the provided resume text into a high-quality Markdown format suitable for submission by a recruitment agency to hiring companies.

【1. PERSONAL DATA REMOVAL - STRICTLY FOLLOW】

Remove or modify ALL of the following personal information:

1. **Full Name → First Name Only**
   - Keep ONLY the first name (given name)
   - Remove last name (family name / surname)
   - Examples: "John Smith" → "John", "Taro Yamada" → "Taro", "Wei-Lin Chen" → "Wei-Lin"

2. **Phone numbers**: Remove any format (e.g., +1-555-123-4567, (03) 1234-5678, 090-1234-5678)

3. **Detailed addresses**: Remove full street addresses, postal codes, apartment/unit numbers. Keep only general location (city or prefecture) for the header.

4. **Email addresses**: Remove completely (e.g., john@example.com)

5. **All profile and social URLs**: Remove LinkedIn, GitHub, Twitter/X, Qiita, personal blogs, portfolio sites, and any other personal URLs

6. **Annotations and timestamps**: Remove notes such as "Resume (PII Removed)", generation timestamps, or any metadata annotations

7. **Personal attributes (compliance-sensitive)**: Remove date of birth, age, gender, nationality, marital status, religion, photo references, or any other protected characteristics. These must not appear in the output.

8. **References**: Remove any "References available upon request" statements and any listed references (names, titles, contact info of referees)

【2. COMPANY NAME PRESERVATION】

- Do NOT anonymize or remove company names mentioned in the resume
- Keep all company names, university names, and project names exactly as they appear

【3. SECTION STRUCTURE - RECONSTRUCT IN THIS ORDER】

Reorganize the resume into the following sections, in this exact order.
**Important**: Remove any original "Objective", "Summary", "Profile", or "About Me" section from the input — the Professional Summary below replaces them entirely. Do NOT output both.

1. **Header**: Output as simple key-value lines. Include only items that exist in the original resume:
   - **Name**: First name only (given name)
   - **Location**: City/prefecture and country (e.g., "Tokyo, Japan")
   - **Visa**: Visa status (e.g., "Engineer/Specialist in Humanities", "Permanent Resident")
   - **Key Credentials**: Only if present (e.g., CPA, CMA, PMP)
   - Do NOT include any title like "Resume", "CV", "Resume (PII Removed)", or any generation timestamps/metadata

2. **Professional Summary** (CREATE NEW — replaces any existing Objective/Summary):
   Write a 2-3 line factual summary **in third person** that lists only verifiable facts from the resume:
   - Total years of experience and primary job titles held
   - Key technical domains and industries worked in
   - Notable quantified achievements (only if explicitly stated in the resume)
   - Do NOT add adjectives like "seasoned", "passionate", "driven", or "exceptional"
   - Do NOT characterize skill combinations as "rare" or "unique"
   - Do NOT fabricate or embellish any credentials, achievements, or descriptions

3. **Experience**: List in reverse chronological order.
   - If the candidate was promoted within the same company, group all roles under a single company section with clear timeline indicators for each role
   - Each bullet should follow the pattern: Action Verb + What was done + Scale/Scope + Result/Impact

4. **Skills**: Analyze the candidate's background and categorize skills into logical groups. Suggested categories include (but are not limited to):
   - Languages (programming languages)
   - Frameworks & Libraries
   - Data & AI/ML (include AI tools such as Claude, ChatGPT, GitHub Copilot, Gemini, Cursor, etc. in this category — these are high-demand skills and should be prominently listed here, NOT buried under "Other")
   - Infrastructure & DevOps
   - Cloud & Platforms
   - Mobile & Frontend
   - IT Strategy & Security
   Only include categories that are relevant. Omit empty categories entirely.
   **IMPORTANT — No Duplicates**: Each skill must appear in exactly ONE category. If a skill (e.g., Git, Shell/Bash, Docker) could fit multiple categories, place it in the single most relevant one and do not repeat it elsewhere.

5. **Language Proficiency & Visa Status** (if mentioned in the resume):
   - Japanese proficiency level (e.g., JLPT N1, N2, business level, conversational, native)
   - Other language proficiencies
   - Visa status (e.g., Permanent Resident, Engineer/Specialist in Humanities visa, etc.)
   If no language or visa information is present in the resume, omit this section entirely.

6. **Education & Certifications**

【4. FORMATTING PRINCIPLES】

Apply these formatting rules:

- Start each achievement bullet with an **Action Verb** (Led, Built, Designed, Implemented, Managed, etc.)
- **Bold** all numerical achievements and metrics (e.g., **5M JPY**, **50% increase**, **$8.1M**, **20-person team**)
- Do NOT add subjective adjectives like "seasoned", "exceptional", "passionate", "driven"
- Do NOT characterize skills as "rare", "unique", or "hard to find"
- Preserve the candidate's original wording where possible — do NOT embellish
- **Date format**: Standardize all dates to "MMM YYYY" format (e.g., "Apr 2022", "Jan 2020"). Convert any other format (2022/04, 04/2022, 2022年4月) to this standard.
- Use ## for major section headings, ### for sub-headings (company names, job titles)
- Use bullet points (-) for listing items
- Use tables where appropriate (e.g., for skills)
- Separate sections with blank lines

【5. HANDLING MISSING METRICS】

- If the original resume contains numerical metrics, preserve and bold them
- If the original resume lacks specific numbers, describe impact qualitatively but accurately (e.g., "Significantly reduced deployment time" or "Expanded client base across the APAC region")
- Do NOT invent or fabricate metrics, percentages, dollar amounts, or team sizes that are not present in the original resume

【6. READABILITY IMPROVEMENTS】

- Fix any OCR scan artifacts: broken line breaks, garbled characters, or incorrectly split sections
- Ensure logical flow and consistent formatting throughout
- If dates or timelines appear inconsistent, preserve the original data but arrange it in a clean, readable format
- **Mixed-language handling**: If the resume contains non-English text (e.g., Japanese company descriptions or job duties), translate them into natural English while preserving the original meaning. Keep proper nouns (company names, product names) in their commonly used form.

【CRITICAL INSTRUCTIONS】
- Do NOT anonymize company names, university names, or project names
- Output the resume in English
- If information for a section does not exist in the original resume, omit that section entirely (do NOT write "N/A" or "Not available")
- Every claim in the Professional Summary and Experience must be grounded in the original resume content
- Do NOT add marketing language, subjective evaluation, or embellishment

【INPUT RESUME】
{resume_text}

【OUTPUT】
Output the processed resume with personal data removed, restructured and formatted as clean Markdown.
"""


def get_jd_transformation_prompt(jd_text: str) -> str:
    """求人票変換用のプロンプトを生成（日本語→英語）"""

    return f"""あなたは外国人エンジニア採用に精通したリクルーターです。
日本企業の求人票（JD）を、海外のエンジニアにとって魅力的な英語の求人票に変換してください。

【変換のポイント】
1. **構成の再構築**: 外国人エンジニアが重視する項目を冒頭に配置
2. **トーンの調整**: 堅苦しい日本語表現を避け、魅力的で親しみやすい英語に
3. **重要情報の明確化**: ビザ、リモートワーク、言語サポートを明示

【出力フォーマット】
以下の構造で出力してください：

---

# [Position Title] at [Company Name]

## Quick Facts
| | |
|---|---|
| **Visa Sponsorship** | Available (supported for qualified candidates) |
| **Remote Work** | (Full Remote/Hybrid/On-site - specify policy) |
| **Language Requirements** | (English OK/Japanese N2+/Bilingual environment) |
| **Salary Range** | (If available, convert to USD range as reference) |
| **Location** | |

## Why Join Us?
(2-3 compelling sentences about the company culture, growth opportunity, or unique value proposition)

## What You'll Do
(Key responsibilities in bullet points - focus on impact, not just tasks)

## What We're Looking For
**Must-have:**
・

**Nice-to-have:**
・

## Benefits & Perks
(Highlight benefits that appeal to international candidates)

## About the Company
(Brief company introduction)

## How to Apply
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

Interested in this position? Value Create will recommend you directly to the company's hiring team.
Please reach out to one of our team members to express your interest:
・**Ilya**
・**Hiroshi**
・**Shu**
We'll take care of the introduction and guide you through the process!

---

【元の求人票】
{jd_text}

上記を解析し、外国人エンジニアに魅力的な英語JDに変換してください。
不明な項目は「To be discussed」または「Contact for details」としてください。
**重要**: Visa Sponsorshipは、元の求人票に記載がなくても「Available (supported for qualified candidates)」と記載してください。Value Createが扱う求人は全てビザサポート対応企業です。
**重要**: 「How to Apply」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用し、各項目の文頭は大文字で始めてください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
"""


def get_jd_en_to_jp_prompt(jd_text: str) -> str:
    """求人票変換用のプロンプトを生成（英語→日本語）"""

    return f"""あなたは人材紹介のエキスパートコンサルタントです。
海外企業や外資系企業の英語求人票（Job Description）を、日本人エンジニアにとって分かりやすく魅力的な日本語の求人票に変換してください。

【変換のポイント】
1. **情報の整理**: 日本の求人票フォーマットに合わせて構造化
2. **トーンの調整**: 自然な日本語表現で、親しみやすく魅力的に
3. **重要情報の明確化**: 勤務条件、待遇、技術スタックを分かりやすく

【出力フォーマット】
以下の構造で出力してください：

---

# [会社名] - [職種名]

## 概要
| 項目 | 内容 |
|------|------|
| **勤務形態** | （フルリモート/ハイブリッド/出社） |
| **勤務地** | |
| **雇用形態** | （正社員/契約社員など） |
| **想定年収** | （円換算の目安も併記） |
| **英語力** | （必須/あれば尚可/不要） |

## 会社について
（会社の事業内容、規模、特徴を2-3文で）

## 仕事内容
（具体的な業務内容を箇条書きで）
・
・

## 必須スキル・経験
・
・

## 歓迎スキル・経験
・
・

## 技術スタック
| カテゴリ | 技術 |
|---------|------|
| 言語 | |
| フレームワーク | |
| インフラ | |
| ツール | |

## 福利厚生・働き方
・
・

## 選考プロセス
（記載があれば）

## 応募方法
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

この求人に興味がある方は、Value Createが直接企業へ推薦いたします。
以下のチームメンバーまでお気軽にご連絡ください：
・**Ilya（イリヤ）**
・**Hiroshi（ヒロシ）**
・**Shu（シュウ）**
面談調整から選考サポートまで、一貫してお手伝いいたします！

---

【元の求人票（英語）】
{jd_text}

上記を解析し、日本人エンジニアに分かりやすい日本語求人票に変換してください。
不明な項目は「要確認」または「詳細はお問い合わせください」としてください。
**重要**: 給与がUSDなどの外貨の場合は、参考として日本円換算も併記してください（1USD≒150円目安）。
**重要**: 「応募方法」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
"""


def get_jd_jp_to_jp_prompt(jd_text: str) -> str:
    """求人票フォーマット化用のプロンプトを生成（日本語→日本語）"""

    return f"""あなたは人材紹介のエキスパートコンサルタントです。
日本語の求人票を、統一された見やすいフォーマットの魅力的な日本語求人票に変換してください。

【変換のポイント】
1. **フォーマットの統一**: 読みやすく整理された構造に再構成
2. **情報の明確化**: 勤務条件、待遇、技術スタックを分かりやすく整理
3. **魅力的な表現**: エンジニアが興味を持つポイントを強調

【出力フォーマット】
以下の構造で出力してください：

---

# [会社名] - [職種名]

## 概要
| 項目 | 内容 |
|------|------|
| **勤務形態** | （フルリモート/ハイブリッド/出社） |
| **勤務地** | |
| **雇用形態** | （正社員/契約社員など） |
| **想定年収** | |
| **英語力** | （必須/あれば尚可/不要） |

## 会社について
（会社の事業内容、規模、特徴を2-3文で）

## 仕事内容
（具体的な業務内容を箇条書きで）
・
・

## 必須スキル・経験
・
・

## 歓迎スキル・経験
・
・

## 技術スタック
| カテゴリ | 技術 |
|---------|------|
| 言語 | |
| フレームワーク | |
| インフラ | |
| ツール | |

## 福利厚生・働き方
・
・

## 選考プロセス
（記載があれば）

## 応募方法
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

この求人に興味がある方は、Value Createが直接企業へ推薦いたします。
以下のチームメンバーまでお気軽にご連絡ください：
・**Ilya（イリヤ）**
・**Hiroshi（ヒロシ）**
・**Shu（シュウ）**
面談調整から選考サポートまで、一貫してお手伝いいたします！

---

【元の求人票（日本語）】
{jd_text}

上記を解析し、統一されたフォーマットの魅力的な日本語求人票に変換してください。
不明な項目は「要確認」または「詳細はお問い合わせください」としてください。
**重要**: 「応募方法」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
"""


def get_jd_en_to_en_prompt(jd_text: str) -> str:
    """求人票フォーマット化用のプロンプトを生成（英語→英語）"""

    return f"""You are an expert recruiter specializing in international engineer recruitment.
Transform the provided English job description into an attractive, well-structured English JD that appeals to international engineers.

【Key Transformation Points】
1. **Restructure the format**: Place information that international engineers prioritize at the top
2. **Enhance readability**: Use clear, engaging language with consistent formatting
3. **Clarify key information**: Explicitly state visa support, remote work policy, and language requirements
4. **Highlight appeal**: Emphasize growth opportunities, tech stack, and company culture

【Output Format】
Please output in the following structure:

---

# [Position Title] at [Company Name]

## Quick Facts
| | |
|---|---|
| **Visa Sponsorship** | Available (supported for qualified candidates) |
| **Remote Work** | (Full Remote/Hybrid/On-site - specify policy) |
| **Language Requirements** | (English OK/Japanese N2+/Bilingual environment) |
| **Salary Range** | (If available, include in USD) |
| **Location** | |

## Why Join Us?
(2-3 compelling sentences about company culture, growth opportunity, or unique value proposition)

## What You'll Do
(Key responsibilities in bullet points - focus on impact, not just tasks)
・
・

## What We're Looking For
**Must-have:**
・
・

**Nice-to-have:**
・
・

## Benefits & Perks
(Highlight benefits that appeal to international candidates)
・
・

## About the Company
(Brief company introduction)

## How to Apply
**※Please use this fixed template (ignore any contact information in the original JD):**

Interested in this position? Value Create will recommend you directly to the company's hiring team.
Please reach out to one of our team members to express your interest:
・**Ilya**
・**Hiroshi**
・**Shu**
We'll take care of the introduction and guide you through the process!

---

【Original Job Description】
{jd_text}

Please analyze the above JD and transform it into an attractive English job description for international engineers.
For unclear items, use "To be discussed" or "Contact for details".
**IMPORTANT**: For Visa Sponsorship, even if not mentioned in the original JD, state "Available (supported for qualified candidates)". All positions handled by Value Create offer visa support.
**IMPORTANT**: For the "How to Apply" section, ignore any contact information or email addresses in the original JD and use the fixed template above (contact Value Create team).
**IMPORTANT**: Use middle dots (・) for list items and capitalize the first letter of each item. Do not use asterisks (*).
**IMPORTANT**: Do not use emojis in headings. Output simple text only.
"""


def get_jd_anonymize_prompt(jd_text: str, anonymize: str, output_lang: str) -> str:
    """求人票匿名化用のプロンプトを生成（入力言語自動検出、出力言語選択可能）"""

    if anonymize == "full":
        anonymize_instruction_ja = """
【完全匿名化処理 - 必須】
以下の情報を必ず匿名化してください：

■ 企業情報 → 業界・規模で表現
- 企業名（正式名称・通称・略称すべて） → 業界+規模に変換（例：「Google」→「米国大手テック企業」「楽天」→「国内大手IT企業」「メルカリ」→「国内フリマアプリ大手」）
- スタートアップ → 「〇〇領域スタートアップ」
- 外資系 → 「外資系〇〇企業」
- 子会社・グループ会社名 → 「大手〇〇企業グループ」
- 企業URL・コーポレートサイト → 削除

■ プロダクト・プロジェクト情報 → 汎用化
- 具体的なプロダクト名 → 「大規模ECプラットフォーム」「FinTechアプリ」など汎用表現に
- 社内プロジェクト名・コードネーム → 削除
- クライアント名 → 「大手〇〇業クライアント」

■ 所在地 → 地域レベルのみ
- 具体的なオフィス住所 → 都道府県・都市名まで（例：「東京都渋谷区〇〇ビル」→「東京都」）
- 海外の場合 → 都市名まで（例：「San Francisco, CA」）

■ 連絡先 → すべて削除
- メールアドレス → 削除
- 電話番号 → 削除
- 担当者名 → 削除
- 採用ページURL → 削除
"""
        anonymize_instruction_en = """
【FULL ANONYMIZATION - REQUIRED】
You MUST anonymize the following information:

■ Company Information → Use Industry/Size Description
- Company name (all variations: official, brand, abbreviations) → Convert to industry + size (e.g., "Google" → "Major US Tech Company", "Rakuten" → "Leading Japanese E-commerce Company")
- Startups → "[Industry] Startup"
- Foreign companies → "Foreign [Industry] Company"
- Subsidiaries → "Major [Industry] Group Company"
- Company URL/website → Remove

■ Product/Project Information → Generalize
- Specific product names → "Large-scale E-commerce Platform", "FinTech App", etc.
- Internal project names/code names → Remove
- Client names → "Major [Industry] Client"

■ Location → Region Level Only
- Specific office address → City/prefecture only (e.g., "Shibuya, Tokyo" → "Tokyo")
- Overseas → City only (e.g., "San Francisco, CA")

■ Contact Information → Remove All
- Email addresses → Remove
- Phone numbers → Remove
- Contact person names → Remove
- Career page URLs → Remove
"""
    elif anonymize == "light":
        anonymize_instruction_ja = """
【軽度匿名化処理 - 必須】
以下の連絡先情報のみ匿名化してください（企業名・プロダクト名は残す）：

- メールアドレス → 削除
- 電話番号 → 削除
- 担当者の個人名 → 削除
- 採用ページURL → 削除

※ 企業名、プロダクト名、オフィス所在地はそのまま残してください。
"""
        anonymize_instruction_en = """
【LIGHT ANONYMIZATION - REQUIRED】
Only remove contact information (keep company and product names):

- Email addresses → Remove
- Phone numbers → Remove
- Personal contact names → Remove
- Career page URLs → Remove

※ Keep company names, product names, and office locations as-is.
"""
    else:
        anonymize_instruction_ja = "【匿名化処理】不要です。すべての情報をそのまま残してください。"
        anonymize_instruction_en = "【NO ANONYMIZATION】Keep all information as-is."

    if output_lang == "ja":
        anonymize_instruction = anonymize_instruction_ja

        if anonymize == "full":
            company_heading = "[業界・規模の表現] - [職種名]"
        else:
            company_heading = "[会社名] - [職種名]"

        return f"""あなたは人材紹介のエキスパートコンサルタントです。
求人票（日本語・英語どちらでも可）を読み取り、匿名化処理を施した上で、統一された見やすいフォーマットの日本語求人票に変換してください。

入力が英語の場合は日本語に翻訳して出力してください。

{anonymize_instruction}

【出力フォーマット】
以下の構造で出力してください：

---

# {company_heading}

## 概要
| 項目 | 内容 |
|------|------|
| **勤務形態** | （フルリモート/ハイブリッド/出社） |
| **勤務地** | |
| **雇用形態** | （正社員/契約社員など） |
| **想定年収** | |
| **英語力** | （必須/あれば尚可/不要） |

## 会社について
（会社の事業内容、規模、特徴を2-3文で。匿名化時は企業特定につながる情報を含めないこと）

## 仕事内容
（具体的な業務内容を箇条書きで）
・
・

## 必須スキル・経験
・
・

## 歓迎スキル・経験
・
・

## 技術スタック
| カテゴリ | 技術 |
|---------|------|
| 言語 | |
| フレームワーク | |
| インフラ | |
| ツール | |

## 福利厚生・働き方
・
・

## 選考プロセス
（記載があれば）

## 応募方法
**※このセクションは以下の固定文言を必ず使用してください（元の求人票の連絡先は無視）：**

この求人に興味がある方は、Value Createが直接企業へ推薦いたします。
以下のチームメンバーまでお気軽にご連絡ください：
・**Ilya（イリヤ）**
・**Hiroshi（ヒロシ）**
・**Shu（シュウ）**
面談調整から選考サポートまで、一貫してお手伝いいたします！

---

【元の求人票】
{jd_text}

上記を解析し、匿名化処理を施した日本語求人票に変換してください。
不明な項目は「要確認」または「詳細はお問い合わせください」としてください。
**重要**: 「応募方法」セクションは、元の求人票に記載されている連絡先やメールアドレスを無視し、上記フォーマットの固定文言（Value Createチームへの連絡）を必ず使用してください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。アスタリスク（*）は使用しないでください。
**重要**: 見出しに絵文字は使用しないでください。シンプルなテキストのみで出力してください。
**重要**: 匿名化レベルに従い、企業名や連絡先の匿名化を厳守してください。本文中に企業名が出現する箇所もすべて匿名化してください。
"""
    else:
        anonymize_instruction = anonymize_instruction_en

        if anonymize == "full":
            company_heading = "[Industry/Size Description]"
        else:
            company_heading = "[Company Name]"

        return f"""You are an expert recruiter specializing in international engineer recruitment.
Read the provided job description (in Japanese or English) and transform it into an anonymized, well-structured English JD that appeals to international engineers.

If the input is in Japanese, translate it to English for the output.

{anonymize_instruction}

【Output Format】
Please output in the following structure:

---

# [Position Title] at {company_heading}

## Quick Facts
| | |
|---|---|
| **Visa Sponsorship** | Available (supported for qualified candidates) |
| **Remote Work** | (Full Remote/Hybrid/On-site - specify policy) |
| **Language Requirements** | (English OK/Japanese N2+/Bilingual environment) |
| **Salary Range** | (If available, include in USD) |
| **Location** | |

## Why Join Us?
(2-3 compelling sentences about the company/team. When anonymized, do not include information that could identify the specific company)

## What You'll Do
(Key responsibilities in bullet points - focus on impact, not just tasks)
・
・

## What We're Looking For
**Must-have:**
・
・

**Nice-to-have:**
・
・

## Benefits & Perks
(Highlight benefits that appeal to international candidates)
・
・

## About the Company
(Brief company introduction. When anonymized, describe only industry, scale, and culture without identifying the company)

## How to Apply
**※Please use this fixed template (ignore any contact information in the original JD):**

Interested in this position? Value Create will recommend you directly to the company's hiring team.
Please reach out to one of our team members to express your interest:
・**Ilya**
・**Hiroshi**
・**Shu**
We'll take care of the introduction and guide you through the process!

---

【Original Job Description】
{jd_text}

Please analyze the above JD and transform it into an anonymized English job description for international engineers.
For unclear items, use "To be discussed" or "Contact for details".
**IMPORTANT**: For Visa Sponsorship, even if not mentioned in the original JD, state "Available (supported for qualified candidates)". All positions handled by Value Create offer visa support.
**IMPORTANT**: For the "How to Apply" section, ignore any contact information or email addresses in the original JD and use the fixed template above (contact Value Create team).
**IMPORTANT**: Use middle dots (・) for list items and capitalize the first letter of each item. Do not use asterisks (*).
**IMPORTANT**: Do not use emojis in headings. Output simple text only.
**IMPORTANT**: Strictly follow the anonymization level. Anonymize company names and contact info throughout the entire text, including mentions in the body.
"""


def get_company_intro_prompt(company_text: str) -> str:
    """会社紹介資料から企業紹介文を生成するプロンプト"""

    return f"""あなたは人材紹介会社のエキスパートコンサルタントです。
会社紹介資料（PDF等から抽出したテキスト）を読み取り、求職者に向けた簡潔で魅力的な企業紹介文を作成してください。

【作成のポイント】
1. **簡潔さ**: 長くても500文字程度に要約
2. **魅力的な表現**: 求職者が興味を持つポイントを強調
3. **事実ベース**: 資料に記載された情報のみを使用

【出力フォーマット】
以下の構造で出力してください：

---

## 企業概要

### 基本情報
| 項目 | 内容 |
|------|------|
| 会社名 | |
| 設立 | |
| 従業員数 | |
| 本社所在地 | |
| 事業内容 | |

### 企業の特徴・強み
（2-3つの箇条書きで、会社の特徴や魅力を記載）
・
・

### こんな方におすすめ
（どんなタイプの求職者に向いているか）
・
・

### 紹介文（求職者向け）
（150-200文字程度の簡潔な紹介文）

---

【会社紹介資料の内容】
{company_text}

上記の資料を解析し、求職者向けの企業紹介文を作成してください。
資料に記載がない項目は「資料に記載なし」としてください。
**重要**: リスト項目の行頭記号は中黒（・）を使用してください。
**重要**: 見出しに絵文字は使用しないでください。
**重要**: 誇張や推測は避け、資料の内容に基づいた正確な情報のみを記載してください。
"""


def get_matching_analysis_prompt(resume_text: str, jd_text: str) -> str:
    """レジュメ×求人票マッチング分析用のプロンプトを生成"""

    return f"""あなたは人材紹介のマッチング分析担当です。
候補者のレジュメと企業の求人票を事実ベースで比較し、客観的な分析レポートを作成してください。

【重要】
- スコアや点数による評価は行わないでください
- 推薦文やアドバイスなど主観的なコメントは含めないでください
- レジュメと求人票に記載された事実のみを抽出・比較してください
- 解釈や推測を加えないでください

【出力フォーマット - 厳守】
以下の構造で必ず出力してください：

---

# マッチング分析レポート

## スキルマッチ詳細

| 技術カテゴリ | 求人要件 | 候補者スキル | 判定 |
|------------|---------|------------|------|
| プログラミング言語 | | | ✅/⚠️/❌ |
| AI/MLフレームワーク | （PyTorch, TensorFlow, JAX等） | | |
| モデル種別・専門領域 | （LLM, CV, NLP, RL, RAG等） | | |
| MLOps/推論基盤 | （MLflow, SageMaker, TensorRT等） | | |
| データ基盤 | （Spark, Airflow, BigQuery等） | | |
| フレームワーク（Web等） | | | |
| データベース | | | |
| インフラ/クラウド | | | |
| その他技術 | | | |

*※ 求人・候補者に該当カテゴリがない場合はその行を省略*

**判定記号の意味**:
- ✅ 求人要件に対して経験あり
- ⚠️ 関連技術の経験はあるが直接の経験なし
- ❌ 該当する経験の記載なし

---

## 経験年数・キャリアレベル

| 項目 | 求人要件 | 候補者（レジュメ記載） |
|-----|---------|---------------------|
| 総エンジニア経験 | | |
| AI/ML領域の経験 | （該当する場合のみ記載） | |
| 該当領域の経験 | | |
| リーダーシップ | | |
| 研究実績・論文 | （該当する場合のみ記載） | |
| 言語レベル | | |

---

## 求人要件との一致点

候補者のレジュメに記載されている経験・スキルのうち、求人要件と一致する事実を列挙：

1. **[一致点1]**: レジュメの記載内容と求人要件の対応を記載
2. **[一致点2]**: 同上
3. **[一致点3]**: 同上

*レジュメに記載された事実のみを引用。解釈や評価は加えない*

---

## 求人要件との差分

求人要件に記載されているがレジュメに該当する記載がない項目を列挙：

1. **[差分1]**: 求人要件の内容と、レジュメ側の状況を記載
2. **[差分2]**: 同上

*差分がない場合は「求人要件に対して未記載の項目なし」と記載*

---

【分析対象】

■ 候補者レジュメ:
{resume_text}

■ 求人票:
{jd_text}

---

【分析指示】
1. 上記フォーマットに厳密に従って出力してください
2. スコア・点数・星評価は一切出力しないでください
3. 「推薦」「アドバイス」「ポテンシャル」「期待」などの主観的な表現は使わないでください
4. レジュメと求人票に書かれている事実のみを比較してください
5. 数値や具体的な経験があれば正確に引用してください
6. AI/ML固有の指標（モデル精度、推論レイテンシ、学習データ規模等）があればそのまま引用してください
7. 見出しに絵文字は使用しないでください（判定記号としての絵文字は可）
8. リスト項目の行頭記号は番号またはハイフン（-）を使用してください
"""


def get_translate_to_english_prompt(japanese_text: str) -> str:
    """日本語→英語翻訳用のプロンプトを生成"""
    return f"""あなたはプロフェッショナルな翻訳者です。
以下の日本語の文書を英語に翻訳してください。

【翻訳指示】
1. ビジネス文書として適切な英語表現を使用
2. Markdown形式を維持（見出し、表、リストなど）
3. 専門用語は適切な英語表現に翻訳
4. 絵文字や記号（✅⚠️❌など）はそのまま保持
5. 数値やスコアはそのまま保持
6. 表の構造を崩さないように注意
7. 自然で読みやすい英語にしてください

【翻訳対象の日本語文書】
{japanese_text}
"""


def get_translate_to_japanese_prompt(english_text: str) -> str:
    """英語→日本語翻訳用のプロンプトを生成"""
    return f"""あなたはプロフェッショナルな翻訳者です。
以下の英語の文書を日本語に翻訳してください。

【翻訳指示】
1. ビジネス文書として適切な日本語表現を使用
2. Markdown形式を維持（見出し、表、リストなど）
3. 専門用語は適切な日本語表現に翻訳
4. 絵文字や記号（✅⚠️❌など）はそのまま保持
5. 数値やスコアはそのまま保持
6. 表の構造を崩さないように注意
7. 自然で読みやすい日本語にしてください

【翻訳対象の英語文書】
{english_text}
"""


def get_anonymous_proposal_prompt(matching_result: str, resume_text: str, jd_text: str, language: str = "ja", anonymize_level: str = "full") -> str:
    """匿名提案資料生成用のプロンプトを生成

    anonymize_level: "full" = 完全匿名化, "light" = 企業名・大学名を表示（個人情報のみ匿名化）
    """

    if language == "ja":
        if anonymize_level == "light":
            anonymize_note = """【匿名化ルール（軽度匿名化モード）】
- 氏名・連絡先（メール、電話番号、住所）は匿名化する
- **企業名・大学名・プロジェクト名・製品名はそのまま記載してよい**
- 経歴の具体的な内容（役職、チーム規模、成果数値など）もそのまま記載してよい"""
        else:
            anonymize_note = """【匿名化ルール（完全匿名化モード）】
- 氏名、企業名、大学名、固有名詞は一切記載しない
- 企業名は「大手SIer」「外資系IT企業」などの一般表現に置換する
- 大学名は「国内トップ大学」「海外有名大学」などに置換する"""

        return f"""あなたはIT・専門職領域に強いハイクラス人材エージェントです。
以下のマッチング分析結果とレジュメ、求人票から、クライアント企業への推薦用に候補者の「市場価値を最大化」した**候補者紹介資料**を作成してください。

【重要】
- レジュメと求人票に記載された事実をベースにしてください
- 「優秀」「卓越」等の漠然とした主観的形容は使わないでください
- 語学力は資格名だけでなく、実務での活用状況を文脈から読み取って補足してください
- AIツールの活用やモダンな開発手法（Agile/DevOps等）があれば必ず強調してください

【入力情報】
■ マッチング分析結果:
{matching_result}

■ レジュメ:
{resume_text}

■ 求人票:
{jd_text}

---

【出力フォーマット】※厳密に従ってください

# 候補者紹介資料

## 1. 見出し
候補者の直近の役職、総経験年数、主要技術領域を1行で記載。
形式：「[直近の役職] | 経験[X]年 | [主要技術領域]」
例：「MLエンジニア | 経験10年 | LLMパイプライン・プロダクションML」
※ 漠然とした主観的な形容（「優秀な」「卓越した」等）は使わず、具体的に書く

---

## 2. Professional Summary（200文字程度）
候補者の最大の「売り」を経験年数×技術×強みの掛け合わせで記載
- 総エンジニア経験年数
- 経験した役職と業界
- レジュメに明記されている定量的な実績
- 言語能力（資格名だけでなく実務での活用状況を文脈から読み取って補足。例：「JLPT N2。日本語での仕様書作成経験あり」）
- AIツール活用やモダン開発手法（Agile/DevOps等）があれば強調

---

## 3. Technical Skills（200文字程度）
求人要件に記載されたスキル・経験のうち、レジュメに該当する記載があるものをカテゴリ別に整理
- Languages, Frameworks, Tools, Cloud/Infra, AI/ML等に分類
- スキル名と、レジュメでの使用実績を対応づけて記載
- 該当なしの場合は「該当するスキルの記載なし」と記載

---

## 4. 学歴・研究実績・資格（200文字程度）
レジュメに記載された学歴・研究・資格の事実
- 最終学歴（大学名・専攻）
- 論文・発表（ある場合、タイトルと学会名）
- 資格名と取得年
- 記載がない場合は「記載なし」

---

## 5. 求人要件との差分（200文字程度）
求人要件に記載されているがレジュメに該当する記載がない項目
- 差分がない場合は「求人要件に対して未記載の項目なし」

---

## 6. コンサルタント所見（推薦ポイント）（200文字程度）
エージェント視点で、この候補者の注目すべきポイントを3点記載。
レジュメに記載された事実に基づき、以下の観点から記載すること：
- **経験の希少な組み合わせ**: 例「MLエンジニアリング×大規模プロダクション運用×チームマネジメントの三領域を跨ぐ経験」
- **求人ポジションとのフィット**: 例「求人要件のLLMパイプライン構築について、前職で同規模のシステム構築実績あり」
- **付加価値**: 例「日英バイリンガルで海外チームとの橋渡し可能」「Agile/DevOps文化での実務経験あり」
※ 「優秀」「卓越」等の漠然とした形容は使わず、具体的な事実・数字に基づいて記載

---

{anonymize_note}

【その他の注意事項】
1. **文字数厳守**: 各セクションの文字数制限を守る（見出しは1行、他は200文字程度）
2. **事実ベース**: レジュメと求人票に記載された情報をベースにする
3. **具体性重視**: 漠然とした形容は避け、数字・技術名・実績で表現する
4. **簡潔性**: 要点を絞って分かりやすく記載
"""
    else:  # English
        if anonymize_level == "light":
            anonymize_note_en = """【Anonymization Rules (Light Anonymization Mode)】
- Anonymize personal names and contact info (email, phone, address)
- **Company names, university names, project names, and product names may be included as-is**
- Specific career details (job titles, team sizes, achievement metrics) may also be included as-is"""
        else:
            anonymize_note_en = """【Anonymization Rules (Full Anonymization Mode)】
- No real names, company names, university names, or identifiable proper nouns
- Replace company names with generic terms (e.g., "a major global IT firm", "a leading SaaS company")
- Replace university names with generic terms (e.g., "a top US university", "a prestigious Japanese university")"""

        return f"""You are a high-end talent agent specializing in IT and technical professionals.
Create a **candidate introduction document** for the client company that maximizes the candidate's market value, based on the matching analysis result, resume, and job description below.

IMPORTANT:
- Base all claims on facts from the resume and job description
- Do NOT use vague subjective adjectives like "exceptional", "outstanding", "passionate"
- Interpret language proficiency beyond just certification names — describe practical usage from context
- Always highlight AI tool usage and modern development practices (Agile/DevOps) if present

【Input Information】
■ Matching Analysis Result:
{matching_result}

■ Resume:
{resume_text}

■ Job Description:
{jd_text}

---

【Output Format】※Strictly follow this format

# Candidate Introduction

## 1. Headline
State the candidate's most recent job title, total years of experience, and primary domain.
Format: "[Most recent title] | [X] years of experience | [Primary domain]"
Example: "ML Engineer | 10 years | LLM pipelines and production ML systems"
※ No vague subjective adjectives. Be specific.

---

## 2. Professional Summary (approximately 200 characters)
Highlight the candidate's key selling points through the combination of experience × technology × strengths
- Total engineering experience years
- Job titles held and industries worked in
- Quantified achievements explicitly stated in the resume
- Language proficiency (beyond just certification names — interpret practical usage from context. E.g., "JLPT N2. Experience writing technical specifications in Japanese")
- AI tool usage and modern development practices (Agile/DevOps) if present

---

## 3. Technical Skills (approximately 200 characters)
Skills and experience from the resume that correspond to job requirements, organized by category
- Group into: Languages, Frameworks, Tools, Cloud/Infra, AI/ML, etc.
- List each matching skill with evidence from the resume
- If no match, state "No matching skills found in resume"

---

## 4. Education / Research (approximately 200 characters)
Academic background and research as stated in the resume
- Highest education (university, major)
- Publications (if any, with venue names)
- Certifications with year obtained
- Write "Not stated in resume" if missing

---

## 5. Gaps vs Job Requirements (approximately 200 characters)
Job requirements not evidenced in the resume
- List specific requirements with no corresponding resume entry
- If no gaps, state "All job requirements have corresponding resume entries"

---

## 6. Consultant's View (Key Recommendation Points) (approximately 200 characters)
From the agent's perspective, list 3 noteworthy points about this candidate.
Based on facts stated in the resume, address the following angles:
- **Rare combination of experience**: E.g., "Spans three domains: ML engineering × large-scale production operations × team management"
- **Fit with the position**: E.g., "Has built a system of comparable scale to the LLM pipeline construction required in this role"
- **Added value**: E.g., "Bilingual (Japanese/English) capable of bridging overseas teams" or "Hands-on experience in Agile/DevOps culture"
※ Do NOT use vague adjectives like "exceptional" or "outstanding" — support each point with specific facts and numbers

---

{anonymize_note_en}

【Other Important Notes】
1. **Character Limit**: Strictly follow character limits (Headline is 1 line, others ~200 characters)
2. **Fact-based**: Base all claims on information from the resume and job description
3. **Specificity over vagueness**: Use numbers, technology names, and achievements instead of vague adjectives
4. **Brevity**: Focus on key points for clarity
"""


def get_cv_proposal_extract_prompt(resume_text: str, anonymize_level: str = "full") -> str:
    """CV提案用コメント抽出プロンプトを生成（英語・各300文字以内・採用企業訴求型）"""

    if anonymize_level == "light":
        anonymize_rules = """1. **Light Anonymization**: Anonymize personal names and contact info (email, phone, address) only. **Company names, university names, project names, and product names may be kept as-is.** Use actual company/university names from the CV to add credibility."""
    else:
        anonymize_rules = """1. **Complete Anonymization**: No real names, company names, university names, or identifiable proper nouns. Use generic terms (e.g., "a major global IT firm", "a top US university")."""

    return f"""You are a high-end talent agent specializing in IT and technical professionals, creating a candidate proposal document.

Your goal: Extract and organize facts from the CV to maximize the candidate's market value. Use specific numbers, technology names, and achievements for persuasiveness. Do NOT use vague adjectives like "seasoned", "exceptional", "passionate", "driven". Interpret language proficiency beyond just certification names — describe practical usage from context. Highlight AI tools and modern development practices (Agile/DevOps) if present.

【CV/Resume】
{resume_text}

---

【Extraction Principles — Apply to ALL sections】
- **Facts only**: Extract information that is explicitly stated in the CV
- **Preserve numbers**: Include all metrics exactly as stated (team sizes, percentages, revenue, user counts)
- **No embellishment**: Do not rephrase achievements to sound more impressive
- **No inference**: Do not infer skills or achievements not explicitly mentioned
- **If information is missing**: Write "Not stated in CV" — do NOT fill gaps with assumptions

---

【Output Format】※ Strictly follow this format. Each item MUST be within 300 characters (2-4 sentences). Output in English only.

## 1. Headline
State the candidate's most recent job title, total years of experience, and primary technical domain. No marketing language.
Format: "[Most recent title] | [X] years of experience | [Primary domain]"
Example 1: "ML Engineer | 10 years of experience | LLM pipelines and production ML systems"
Example 2: "DevOps Lead | 12 years of experience | Cloud infrastructure and CI/CD"
※ 60-100 characters. No names or company names. No subjective adjectives.

## 2. Professional Summary
Highlight the candidate's key selling points through the combination of experience × technology × strengths. Include total experience, job titles held, industries worked in, key quantified achievements, and language proficiency (interpret practical usage, not just certification names).
Example: "ML Engineer with 8 years of experience. Worked at Company A and Company B. Built a search platform processing 500K+ daily queries. Led a 12-person team. JLPT N2 — writes technical specs in Japanese."
※ 200-300 characters. Facts from the CV.

## 3. Technical Skills
List the candidate's technical skills as stated in the CV, grouped by category. Include years of experience only if explicitly mentioned. Do not infer proficiency levels.
Example: "Languages: Python (8 years), Go (3 years). ML: PyTorch, TensorFlow, Hugging Face. Infrastructure: AWS, Kubernetes, Docker. Data: PostgreSQL, BigQuery."
※ 200-300 characters. Only skills mentioned in the CV.

## 4. Education / Research
List academic degrees, certifications, publications, and competition results exactly as stated in the CV. Do not interpret or embellish.
Example: "M.Sc. in Computer Science from University X. Published 2 papers at NeurIPS. AWS Solutions Architect Professional certified."
※ 200-300 characters. Only facts from the CV. Write "Not stated in CV" for missing sections.

## 5. Key Achievements
List the 2-3 most notable quantified achievements from the CV. Include only achievements with specific metrics or outcomes stated in the CV.
Example: "Reduced inference latency from 200ms to 50ms. Migrated monolith to microservices serving 2M daily users. Cut infrastructure costs by $240K annually."
※ 200-300 characters. Only achievements with metrics from the CV. If no quantified achievements, write "No quantified achievements stated in CV."

## 6. Consultant's View (Key Recommendation Points)
From the agent's perspective, list 3 noteworthy points about this candidate based on facts from the CV:
- **Rare combination of experience**: What makes this candidate's experience profile distinctive (e.g., "Spans ML engineering × production systems × team leadership")
- **Added value**: Practical advantages such as bilingual ability, Agile/DevOps culture experience, AI tool proficiency, cross-functional collaboration
- **Standout achievement**: The single most impressive concrete achievement from the CV, with numbers
Example: "1. Combines 8 years of ML engineering with production-scale deployment (500K+ daily queries) and team leadership (12 engineers). 2. Bilingual (EN/JP) with JLPT N2, writes technical specs in Japanese. 3. Reduced model inference latency by 75% (200ms → 50ms) in production."
※ 200-300 characters. Support each point with specific facts and numbers from the CV. Do NOT use vague adjectives.

---

【Important Rules】
{anonymize_rules}
2. **Character Targets**: Each section (except Headline) should be 200-300 characters (2-4 sentences). Headline MUST be 60-100 characters.
3. **English Only**: All output must be in English.
4. **Fact-based**: Every claim must be grounded in the CV. Do NOT invent metrics, achievements, or experiences. Use specific numbers and technology names instead of vague adjectives.
5. **No Markdown Headers in Values**: Output the value text directly after each header.
6. **Specificity over vagueness**: Express value through concrete facts, not marketing language.
"""


def extract_name_from_cv(text: str) -> str:
    """CVテキストの先頭行から候補者名を抽出する"""
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # 明らかにセクション見出しや連絡先情報はスキップ
        lower = line.lower()
        if any(kw in lower for kw in [
            "resume", "curriculum vitae", "cv", "objective", "summary",
            "experience", "education", "skills", "phone", "email",
            "address", "http", "www.", "@", "linkedin"
        ]):
            continue
        # 数字が多い行（電話番号など）はスキップ
        if sum(c.isdigit() for c in line) > len(line) * 0.3:
            continue
        # 長すぎる行は名前ではない（50文字以下を想定）
        if len(line) > 50:
            continue
        return line
    return ""


def extract_first_name(content: str) -> str:
    """生成済みレジュメからファーストネームを抽出する"""
    for line in content.split('\n')[:15]:
        line = line.strip()
        # **Name**: John  or  Name: John  パターン
        for prefix in ['**Name**:', 'Name:']:
            if prefix in line:
                name = line.split(prefix, 1)[1].strip()
                name = name.strip('*').strip()
                if name:
                    return name
    return ""


def get_adjust_length_prompt(proposal_text: str, target_chars: int) -> str:
    """CV提案コメントの文章量を調整するプロンプトを生成"""

    if target_chars <= 150:
        style = "Very concise — keep only the single most impactful fact per section. 1-2 sentences max."
        catch_copy_range = "50-70"
    elif target_chars <= 200:
        style = "Concise — keep the strongest 2 facts per section. 2 sentences."
        catch_copy_range = "60-80"
    elif target_chars <= 250:
        style = "Moderately concise — keep key facts and brief context. 2-3 sentences."
        catch_copy_range = "60-90"
    elif target_chars <= 300:
        style = "Standard length — provide good detail with context. 3-4 sentences."
        catch_copy_range = "60-100"
    else:
        style = "Detailed — expand with additional context, examples, and qualitative descriptions. 4-5 sentences."
        catch_copy_range = "80-120"

    return f"""You are an elite recruitment consultant. Adjust the length of the following candidate proposal to match the target.

【Current Proposal】
{proposal_text}

---

【Instructions】
- **Target**: Each section (except Catch Copy) should be approximately {target_chars} characters.
- **Style**: {style}
- **Catch Copy**: Keep within {catch_copy_range} characters.
- Keep the same section headers (## 1. Catch Copy, ## 2. Summary, etc.)
- Maintain the same language and anonymization level as the original
- Prioritize: quantified achievements > rare skills > general descriptions
- The result must read naturally — do not sacrifice readability for length
- **Sentence Length (50-80 characters)**: Each sentence MUST be 50-80 characters. Break long sentences into shorter ones, but never shorter than 50 characters. Add specific context (numbers, scope, domain) to short sentences to reach the minimum. One idea per sentence. Do not chain clauses with commas or dashes.
- Output in English only
- Do NOT add any new information not present in the original. When expanding, elaborate on existing facts with more context, do not fabricate.
"""
