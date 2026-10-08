import re

def basic_input_filter(s: str) -> str:
    s = s.strip()
    s = re.sub(r'(?i)ignore (all|previous) instructions', '[redacted]', s)
    s = re.sub(r'(?i)system:|developer:', '[role-removed]', s)
    return s
