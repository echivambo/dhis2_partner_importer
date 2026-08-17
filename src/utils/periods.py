import re
import datetime
from typing import List, Tuple

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

PORTUGUESE_MONTH_NAMES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]

def to_dhis2_period(human_period: str) -> str:
    """
    Converts a human-readable period string into DHIS2 YYYYMM format.
    Supports formats like:
      - "January 2026"
      - "Janeiro 2026"
      - "Jan 2026"
      - "2026-01"
      - "2026/01"
      - "202601"
    """
    if not human_period:
        raise ValueError("Period cannot be empty.")
        
    s = human_period.strip()
    
    # 1. Matches direct YYYYMM digit format (e.g., 202601)
    if re.match(r"^\d{6}$", s):
        year = int(s[:4])
        month = int(s[4:])
        if 1 <= month <= 12:
            return s
            
    # 2. Matches YYYY-MM or YYYY/MM format
    match_iso = re.match(r"^(\d{4})[-/](\d{1,2})$", s)
    if match_iso:
        year = int(match_iso.group(1))
        month = int(match_iso.group(2))
        if 1 <= month <= 12:
            return f"{year}{month:02d}"

    # 3. Matches Month Name Year (e.g. "January 2026", "Janeiro 2026", "Jan 2026")
    # Clean string and extract word parts and digit parts
    words = re.findall(r"[a-zA-Z\u00C0-\u00FF]+", s)
    digits = re.findall(r"\d+", s)
    
    if words and digits:
        year_str = digits[0]
        if len(year_str) == 2:
            # Assume 20xx
            year_str = "20" + year_str
        year = int(year_str)
        
        word_lower = words[0].lower()
        
        # Check English Month Names
        for idx, m in enumerate(MONTH_NAMES):
            if m.lower().startswith(word_lower) or word_lower.startswith(m.lower()[:3]):
                return f"{year}{idx + 1:02d}"
                
        # Check Portuguese Month Names
        for idx, m in enumerate(PORTUGUESE_MONTH_NAMES):
            # Strip accents for comparison
            normalized_m = m.lower().replace("ç", "c")
            normalized_word = word_lower.replace("ç", "c")
            if normalized_m.startswith(normalized_word) or normalized_word.startswith(normalized_m[:3]):
                return f"{year}{idx + 1:02d}"

    raise ValueError(f"Unable to parse period format: '{human_period}'. Expected format like 'January 2026' or '2026-01'.")


def to_human_period(dhis2_period: str, lang: str = "en") -> str:
    """
    Converts a DHIS2 YYYYMM period back to human readable "Month Year" format.
    """
    if not dhis2_period or len(dhis2_period) != 6 or not dhis2_period.isdigit():
        raise ValueError(f"Invalid DHIS2 period: '{dhis2_period}'. Expected YYYYMM format.")
        
    year = dhis2_period[:4]
    month_idx = int(dhis2_period[4:]) - 1
    
    if not (0 <= month_idx < 12):
        raise ValueError(f"Invalid month component in period: '{dhis2_period}'.")
        
    months = PORTUGUESE_MONTH_NAMES if lang.lower() == "pt" else MONTH_NAMES
    return f"{months[month_idx]} {year}"


def generate_readable_periods(years_back: int = 3, lang: str = "en") -> List[Tuple[str, str]]:
    """
    Generates a list of (human_readable, dhis2_period) tuples for dropdown selectors.
    Starts from current month and goes back `years_back` years.
    """
    periods = []
    current_date = datetime.date.today()
    # Go back to start of the current year or specific start
    year = current_date.year
    month = current_date.month
    
    months = PORTUGUESE_MONTH_NAMES if lang.lower() == "pt" else MONTH_NAMES
    
    for _ in range(years_back * 12):
        dhis2_val = f"{year}{month:02d}"
        human_val = f"{months[month - 1]} {year}"
        periods.append((human_val, dhis2_val))
        
        # Decrement month
        month -= 1
        if month == 0:
            month = 12
            year -= 1
            
    return periods
