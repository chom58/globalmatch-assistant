"""
PII除去プロンプトのテストスクリプト

使い方:
  GROQ_API_KEY=gsk_xxxx python test_pii_removal.py
"""

import os
import sys
from groq import Groq
from app import get_resume_pii_removal_prompt

SAMPLE_RESUME = """Resume (PII Removed) - Generated 2025-12-15

Kenji Tanaka
kenji.tanaka@gmail.com
linkedin.com/in/kenji-tanaka-12345
+81-90-1234-5678
3-5-12 Roppongi, Minato-ku, Tokyo 106-0032

OBJECTIVE
Seeking a challenging role in technology leadership.

EXPERIENCE

Mercari, Inc.
Engineering Manager          Apr 2022 - Present
- Managed team of 18 engineers across microservices platform
- Drove migration from monolith to microservices, reducing deploy time by 60%
- Established SRE practices, achieving 99.95% uptime

DevOps Lead                  Jan 2020 - Mar 2022
- Built CI/CD pipelines using GitHub Actions and ArgoCD
- Reduced infrastructure costs by $240K annually through Kubernetes optimization
- Led incident response framework adopted company-wide

Rakuten Group, Inc.
Senior Software Engineer     Jun 2016 - Dec 2019
- Developed payment processing system handling 2M+ daily transactions
- Improved API response time
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
        ("氏名 → First Name化", "Tanaka" not in result and "Kenji" in result),
        ("メール削除", "kenji.tanaka@gmail.com" not in result),
        ("LinkedIn削除", "linkedin.com" not in result),
        ("電話番号削除", "90-1234-5678" not in result),
        ("詳細住所削除", "Roppongi" not in result and "106-0032" not in result),
        ("注釈削除", "PII Removed" not in result and "Generated 2025" not in result),
        ("社名維持 (Mercari)", "Mercari" in result),
        ("社名維持 (Rakuten)", "Rakuten" in result),
        ("社名維持 (Accenture)", "Accenture" in result),
        ("大学名維持 (Keio)", "Keio" in result),
        ("Professional Summary存在", "Summary" in result or "summary" in result),
        ("数値太字化", "**" in result),
        ("Language/Visa セクション", "Japanese" in result and ("Native" in result or "native" in result)),
    ]

    passed = 0
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"  [{status}] {label}")

    print(f"\n  結果: {passed}/{len(checks)} passed")


if __name__ == "__main__":
    main()
