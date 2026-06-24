import re
import requests

_jd_cache = {}

def fetch_job_description(url: str, portal: str, fallback_title: str, skills: str) -> str:
    """Portal-aware JD fetch. Returns clean text or synthetic fallback."""
    if not url:
        return f"{fallback_title} requiring skills: {skills}"

    cache_key = url.split("?")[0].rstrip("/")
    if cache_key in _jd_cache:
        return _jd_cache[cache_key]

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=8)
        if not r.ok:
            raise ValueError(f"HTTP {r.status_code}")

        html = r.text

        if portal == "Naukri":
            m = re.search(r'"jobDescription"\s*:\s*"([^"]+)"', html)
            if m:
                try:
                    result = m.group(1).encode().decode("unicode_escape")[:4000]
                    _jd_cache[cache_key] = result
                    return result
                except Exception:
                    pass

        if portal == "LinkedIn":
            m = re.search(r'"description"\s*:\s*\{[^}]*"text"\s*:\s*"([^"]+)"', html)
            if m:
                try:
                    result = m.group(1).encode().decode("unicode_escape")[:4000]
                    _jd_cache[cache_key] = result
                    return result
                except Exception:
                    pass

        # Generic: strip tags
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        result = text[:4000] if len(text) >= 80 else f"{fallback_title} requiring skills: {skills}"
        _jd_cache[cache_key] = result
        return result

    except Exception:
        return f"{fallback_title} requiring skills: {skills}"
