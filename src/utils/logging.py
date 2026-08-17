import logging
import re
from typing import Any, Dict

def setup_logging(level: int = logging.INFO):
    """
    Sets up the application's logging configuration matching the format:
    YYYY-MM-DD HH:MM:SS LEVEL Message
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler()
        ]
    )
    
    # Set third-party logs (like urllib3) to WARNING level to minimize noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

def scrub_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively scrubs credentials and authorization fields from dictionaries
    before printing or logging them.
    """
    if not isinstance(data, dict):
        return data
        
    scrubbed = {}
    sensitive_keys = {
        'password', 'pwd', 'pat', 'token', 'authorization', 'auth', 
        'client_secret', 'secret', 'credentials'
    }
    
    for k, v in data.items():
        k_lower = k.lower()
        if any(sk in k_lower for sk in sensitive_keys):
            scrubbed[k] = "********"
        elif isinstance(v, dict):
            scrubbed[k] = scrub_sensitive_data(v)
        elif isinstance(v, list):
            scrubbed[k] = [scrub_sensitive_data(item) if isinstance(item, dict) else item for item in v]
        else:
            # Mask URL passwords if embedded in base_url
            if k_lower == 'base_url' and isinstance(v, str):
                scrubbed[k] = re.sub(r'//([^:]+):([^@]+)@', r'//\1:********@', v)
            else:
                scrubbed[k] = v
                
    return scrubbed
