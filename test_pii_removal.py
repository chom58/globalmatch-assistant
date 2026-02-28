"""
PII除去プロンプトのテストスクリプト

使い方:
  GROQ_API_KEY=gsk_xxxx python test_pii_removal.py
"""

import os
import sys
from groq import Groq
from app import get_resume_pii_removal_prompt

# 新ルールを網羅的にテストするサンプルレジュメ
# - 注釈・タイムスタンプ
# - フルネーム、メール、LinkedIn、GitHub、電話、詳細住所
# - 個人属性（DOB, 国籍, 性別）
# - References セクション
# - OBJECTIVEセクション（Professional Summaryに置換されるべき）
# - 同一企業内の昇進（Mercari: EM → DevOps Lead）
# - 日本語混在テキスト
# - 不統一な日付フォーマット（2022/04, Apr 2022, 2016年6月）
SAMPLE_RESUME = """Resume (PII Removed) - Generated 2025-12-15

Kenji Tanaka
kenji.tanaka@gmail.com
linkedin.com/in/kenji-tanaka-12345
github.com/kenji-tanaka
https://kenji-dev.blog
+81-90-1234-5678
3-5-12 Roppongi, Minato-ku, Tokyo 106-0032

Date of Birth: 1990-05-15
Nationality: Japanese
Gender: Male

OBJECTIVE
Seeking a challenging role in technology leadership.

EXPERIENCE

Mercari, Inc.
Engineering Manager          2022/04 - Present
- Managed team of 18 engineers across microservices platform
- Drove migration from monolith to microservices, reducing deploy time by 60%
- Established SRE practices, achieving 99.95% uptime

DevOps Lead                  Jan 2020 - 2022/03
- Built CI/CD pipelines using GitHub Actions and ArgoCD
- Reduced infrastructure costs by $240K annually through Kubernetes optimization
- Led incident response framework adopted company-wide

Rakuten Group, Inc.
Senior Software Engineer     2016年6月 - Dec 2019
- Developed payment processing system handling 2M+ daily transactions
- 大規模決済システムのパフォーマンス改善を実施
- Mentored 5 junior engineers

Accenture Japan Ltd.
IT Consultant                Apr 2013 - May 2016
- Delivered ERP implementation projects for major manufacturing clients
- Conducted IT strategy assessments

SKILLS
Python, Go, TypeScript, Java, Terraform, Docker, Kubernetes,
AWS (ECS, Lambda, RDS, S3), GCP (GKE, BigQuery),
React, Next.js, PostgreSQL, Redis, Datadog, Prometheus,
Grafana, Machine Learning basics, LLM integration,
CISSP, ISO 27001 auditing

CERTIFICATIONS
- AWS Solutions Architect Professional (2021)
- Certified Information Systems Security Professional (CISSP) (2019)
- Certified Public Accountant (CPA), Japan (2012)

EDUCATION
Keio University - B.S. in Economics (2009 - 2013)

LANGUAGE
- Japanese: Native
- English: Business Level (TOEIC 920)

VISA
Permanent Resident

REFERENCES
Available upon request.
Dr. Hiroshi Sato, CTO, Example Corp. - hiroshi.sato@example.com
"""


def main():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY 環境変数を設定してください")
        print("  GROQ_API_KEY=gsk_xxxx python test_pii_removal.py")
        sys.exit(1)

    prompt = get_resume_pii_removal_prompt(SAMPLE_RESUME)

    print("=" * 60)
    print("PII除去プロンプト テスト実行")
    print("=" * 60)
    print(f"Model: llama-3.3-70b-versatile")
    print(f"入力文字数: {len(SAMPLE_RESUME)}")
    print("=" * 60)
    print()

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
        timeout=60,
    )

    result = response.choices[0].message.content
    print(result)

    # チェックポイント検証
    print()
    print("=" * 60)
    print("自動チェック結果")
    print("=" * 60)

    checks = [
        # --- PII除去 ---
        ("氏名 → First Name化", "Tanaka" not in result and "Kenji" in result),
        ("メール削除", "kenji.tanaka@gmail.com" not in result),
        ("LinkedIn削除", "linkedin.com" not in result),
        ("GitHub削除", "github.com/kenji" not in result),
        ("個人ブログ削除", "kenji-dev.blog" not in result),
        ("電話番号削除", "90-1234-5678" not in result),
        ("詳細住所削除", "Roppongi" not in result and "106-0032" not in result),
        ("注釈・タイムスタンプ削除", "PII Removed" not in result and "Generated 2025" not in result),
        # --- 個人属性 (コンプライアンス) ---
        ("生年月日削除", "1990" not in result and "Date of Birth" not in result),
        ("国籍削除", "Nationality" not in result),
        ("性別削除", "Gender: Male" not in result),
        # --- References ---
        ("References削除", "Hiroshi Sato" not in result and "hiroshi.sato@example" not in result),
        ("References文言削除", "Available upon request" not in result),
        # --- 社名・大学名維持 ---
        ("社名維持 (Mercari)", "Mercari" in result),
        ("社名維持 (Rakuten)", "Rakuten" in result),
        ("社名維持 (Accenture)", "Accenture" in result),
        ("大学名維持 (Keio)", "Keio" in result),
        # --- セクション構成 ---
        ("Professional Summary存在", "Summary" in result or "summary" in result),
        ("OBJECTIVE除去", "OBJECTIVE" not in result and "Seeking a challenging" not in result),
        # --- フォーマット ---
        ("数値太字化", "**" in result),
        ("日付フォーマット統一 (MMM YYYY)", "Apr 2022" in result or "Apr 2020" in result),
        # --- Language/Visa ---
        ("Language/Visa セクション", "Japanese" in result and ("Native" in result or "native" in result)),
        ("Visa情報維持", "Permanent Resident" in result),
        # --- 三人称 ---
        ("Professional Summary三人称",
         any(phrase in result for phrase in [
             "A seasoned", "An experienced", "Brings", "a seasoned", "an experienced",
             "with over", "with a rare", "combining", "who has", "the candidate",
             "engineer with", "leader with", "professional with",
         ])),
        # --- 日本語混在→英語変換 ---
        ("日本語テキストの英語化", "大規模決済" not in result),
    ]

    passed = 0
    failed_items = []
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed_items.append(label)
        print(f"  [{status}] {label}")

    print(f"\n  結果: {passed}/{len(checks)} passed")
    if failed_items:
        print(f"  失敗項目: {', '.join(failed_items)}")


if __name__ == "__main__":
    main()
