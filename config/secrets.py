import os

def reload_secrets():
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip()
        except Exception as e:
            print(f"Error loading .env file: {e}")
    
    global GEMINI_API_KEY, LINKEDIN_EMAIL, LINKEDIN_PASSWORD, NAUKRI_EMAIL, NAUKRI_PASSWORD, IMAP_EMAIL, IMAP_PASSWORD, CORP_EMAIL, CORP_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
    LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
    NAUKRI_EMAIL = os.getenv("NAUKRI_EMAIL", "")
    NAUKRI_PASSWORD = os.getenv("NAUKRI_PASSWORD", "")
    IMAP_EMAIL = os.getenv("IMAP_EMAIL", "")
    IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
    CORP_EMAIL = os.getenv("CORP_EMAIL", "")
    CORP_PASSWORD = os.getenv("CORP_PASSWORD", "")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Run on initial import
reload_secrets()
