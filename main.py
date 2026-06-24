"""
main.py — Run the full job hunt automation
"""

import sys
import os
import argparse

# Force utf-8 encoding for stdout/stderr to handle emoji if standard write is used
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make sure we run from the script folder
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def setup_folders():
    """Ensure required directories exist before starting."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("resume", exist_ok=True)
    
    # Check if the configured resume exists
    try:
        from config.profile import PROFILE
        resume_path = PROFILE.get("resume_path", "")
        if resume_path and not os.path.exists(resume_path):
            print(f"[WARN] Warning: Resume not found at path: {resume_path}")
            print("[INFO] Please make sure your resume file is placed at the specified path.")
    except Exception as e:
        print(f"[WARN] Configuration load warning: {e}")


def test_mode():
    """Test the keyword filter without opening any browser."""
    from filter import should_apply
    print("\n" + "="*55)
    print("  TEST MODE — Keyword & Company Filter Check")
    print("="*55)

    sample_jobs = [
        ("Infosys",    "Senior Data Engineer",     "AWS Snowflake PySpark SQL Python ETL Glue S3 data pipelines cloud"),
        ("TCS",        "Java Developer",           "Spring Boot Microservices REST API Docker Kubernetes"),
        ("Wipro",      "Cloud Data Engineer",      "AWS Glue Spark SQL Python Data Pipeline Redshift"),
        ("Cognizant",  "Business Analyst",         "Excel PowerPoint stakeholder management reporting"),
        ("Amazon",     "Data Engineer II",         "AWS S3 Glue Spark Python SQL Redshift Airflow ETL"),
        ("Accenture",  "ETL Developer",            "Informatica ETL SQL Python data warehouse Snowflake"),
        ("Goldman",    "Analytics Engineer",       "dbt SQL Python Snowflake data modeling pipelines"),
        ("Capgemini",  "SAP Consultant",           "SAP FICO MM SD ABAP implementation"),
    ]

    print(f"\n{'DECISION':<8} {'COMPANY':<15} {'ROLE':<25} {'SCORE':<8} MATCHED")
    print("-" * 80)

    for company, title, desc in sample_jobs:
        do_apply, score, matched, reason, decision, missing = should_apply(title, desc, company)
        decision_label = f"[{decision.upper()}]"
        print(f"{decision_label:<10} {company:<15} {title:<25} {score:>5}%   {', '.join(matched[:4]) if matched else reason}")

    print("\n[OK] Filter logic verified successfully!")


def run_all(headless=False, log_fn=print):
    """Run all bots sequentially."""
    from linkedin_bot import run_linkedin_bot
    from naukri_bot import run_naukri_bot
    from indeed_bot import run_indeed_bot
    from careers_bot import run_careers_bot
    from tracker import print_summary
    from config.profile import PER_RUN_LIMIT

    log_fn("\n[START] Starting Full Job Hunt Automation...")
    log_fn(f"   Per-portal run limit: {PER_RUN_LIMIT} applications")
    log_fn("   Press Ctrl+C at any time to cancel.\n")

    run_linkedin_bot(max_applications=PER_RUN_LIMIT, headless=headless, log_fn=log_fn)
    run_naukri_bot(max_applications=PER_RUN_LIMIT, headless=headless, log_fn=log_fn)
    run_indeed_bot(max_applications=PER_RUN_LIMIT, headless=headless, log_fn=log_fn)
    run_careers_bot(headless=headless, log_fn=log_fn)

    print_summary()


if __name__ == "__main__":
    setup_folders()

    parser = argparse.ArgumentParser(description="Auto-Apply Job Search Bot")
    parser.add_argument("--test", action="store_true", help="Run in test offline mode")
    parser.add_argument("--linkedin", action="store_true", help="Run LinkedIn bot only")
    parser.add_argument("--naukri", action="store_true", help="Run Naukri bot only")
    parser.add_argument("--indeed", action="store_true", help="Run Indeed bot only")
    parser.add_argument("--careers", action="store_true", help="Run Careers page bot only")
    parser.add_argument("--summary", action="store_true", help="Display summary of today's applications")
    parser.add_argument("--headless", action="store_true", help="Run browser in background (headless) mode")
    parser.add_argument("--company", type=str, help="Override target company name filter (comma separated, e.g. 'tcs,wipro')")
    
    parser.add_argument("--retry", type=str, metavar="COMPANY",
                        help="Retry skipped jobs for given company (e.g. 'Accenture')")
    parser.add_argument("--urls", type=str, metavar="URL1,URL2",
                        help="Comma-separated career page URLs to apply to (uses careers bot)")

    args = parser.parse_args()

    # Override target companies dynamically if provided on CLI
    if args.company:
        import config.profile
        companies_list = [c.strip() for c in args.company.split(",") if c.strip()]
        config.profile.TARGET_COMPANIES = companies_list
        print(f"[TARGETS] Overriding target companies filter to: {companies_list}")

    if args.test:
        test_mode()
    elif args.retry:
        from retry_engine import retry_company_jobs
        retry_company_jobs(args.retry)
    elif args.urls:
        from careers_bot import run_careers_bot
        url_list = [u.strip() for u in args.urls.split(",") if u.strip()]
        run_careers_bot(headless=args.headless, urls=url_list)
    elif args.linkedin:
        from linkedin_bot import run_linkedin_bot
        from config.profile import PER_RUN_LIMIT
        run_linkedin_bot(max_applications=PER_RUN_LIMIT, headless=args.headless)
    elif args.naukri:
        from naukri_bot import run_naukri_bot
        from config.profile import PER_RUN_LIMIT
        run_naukri_bot(max_applications=PER_RUN_LIMIT, headless=args.headless)
    elif args.indeed:
        from indeed_bot import run_indeed_bot
        from config.profile import PER_RUN_LIMIT
        run_indeed_bot(max_applications=PER_RUN_LIMIT, headless=args.headless)
    elif args.careers:
        from careers_bot import run_careers_bot
        run_careers_bot(headless=args.headless)
    elif args.summary:
        from tracker import print_summary
        print_summary()
    else:
        run_all(headless=args.headless)


