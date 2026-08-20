import io
import logging
import pandas as pd
from typing import Optional
from src.dhis2.client import DHIS2Client

logger = logging.getLogger(__name__)

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renames the columns of the DataFrame to standard internal labels:
    'data_element', 'org_unit', 'period', 'value'.
    Uses synonyms to handle DHIS2 API version differences.
    """
    synonyms = {
        'data_element': ['data', 'data element', 'dataelement', 'dx', 'data_element', 'data_element_uid'],
        'org_unit': ['organisation unit', 'organisationunit', 'orgunit', 'ou', 'organisation_unit', 'org_unit_uid', 'org unit'],
        'period': ['period', 'pe', 'periodo'],
        'value': ['value', 'val', 'valor']
    }
    
    mapping = {}
    for col in df.columns:
        col_clean = str(col).lower().strip()
        matched = False
        
        # 1. Look for exact matches
        for std_name, syn_list in synonyms.items():
            if col_clean in syn_list:
                mapping[col] = std_name
                matched = True
                break
                
        # 2. Look for substring matches if no exact match found
        if not matched:
            for std_name, syn_list in synonyms.items():
                if any(syn in col_clean for syn in syn_list if len(syn) > 2):
                    mapping[col] = std_name
                    break
                    
    df_renamed = df.rename(columns=mapping)
    
    # Check that we have the 4 essential fields
    required = ['data_element', 'org_unit', 'period', 'value']
    missing = [r for r in required if r not in df_renamed.columns]
    if missing:
        raise ValueError(
            f"Could not map columns {missing} to standard names. "
            f"Original columns: {list(df.columns)}"
        )
        
    return df_renamed

def extract_partner_data(client: DHIS2Client, analytics_url_template: str, period: str) -> pd.DataFrame:
    """
    Extracts analytics data from the partner DHIS2 instance using the provided client,
    compiles the URL for the specified period, downloads the CSV, and returns a normalized
    pandas DataFrame.
    """
    # 1. Substitute the {period} placeholder
    compiled_url = analytics_url_template.replace("{period}", period)
    logger.info("Compiled extraction URL for period %s", period)
    
    # 2. Extract the relative path from the absolute URL if it matches the client's base URL
    relative_path = compiled_url
    if client.base_url in compiled_url:
        relative_path = compiled_url.replace(client.base_url, "").lstrip('/')
    elif compiled_url.startswith("http://") or compiled_url.startswith("https://"):
        # Warn if the analytics URL template uses a different domain than the base URL
        logger.warning(
            "Analytics URL template base does not match DHIS2 Client base_url: %s vs %s",
            compiled_url, client.base_url
        )
        # Attempt to split after protocol/domain
        from urllib.parse import urlparse
        parsed = urlparse(compiled_url)
        relative_path = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        relative_path = relative_path.lstrip('/')
        
    logger.debug("Requesting relative path: %s", relative_path)
    
    # 3. Perform authenticated GET request
    response = client.get(relative_path)
    csv_text = response.text
    
    # 4. Check that response content is not empty
    if not csv_text or not csv_text.strip():
        logger.warning("Empty response received from DHIS2 analytics.")
        return pd.DataFrame(columns=['data_element', 'org_unit', 'period', 'value'])
        
    # 5. Parse into DataFrame
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        logger.info("Successfully extracted %d rows from source.", len(df))
    except Exception as e:
        logger.error("Failed to parse CSV response as DataFrame: %s", e)
        raise ValueError(f"Failed to parse CSV response from analytics API: {str(e)}")
        
    # 6. Normalize columns
    try:
        df_normalized = normalize_columns(df)
        logger.debug("DataFrame column normalization successful.")
        return df_normalized
    except Exception as e:
        logger.error("Column normalization failed: %s", e)
        raise
