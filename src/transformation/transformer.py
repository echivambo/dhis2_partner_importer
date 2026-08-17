import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger(__name__)

def transform_partner_data(df: pd.DataFrame, partner_config: Dict[str, Any]) -> pd.DataFrame:
    """
    Transforms the source DataFrame using the partner mappings.
    Returns a new DataFrame with mapped columns and default mappings.
    The original DataFrame is NOT mutated.
    """
    logger.info("Starting data transformation for partner: %s", partner_config.get("name"))
    
    # 1. Ensure immutable transformation by copying the source DataFrame
    transformed_df = df.copy()
    
    # Get partner mappings from config
    mappings = partner_config.get("mappings", {})
    de_mappings = mappings.get("data_elements", {})
    ou_mappings = mappings.get("organisation_units", {})
    coc_mappings = mappings.get("category_option_combos", {})
    
    # Get partner destination configurations
    dest_config = partner_config.get("destination", {})
    aoc_uid = dest_config.get("attribute_option_combo")
    
    # 2. Rename columns to keep tracking of source values
    rename_rules = {
        'data_element': 'source_data_element',
        'org_unit': 'source_org_unit'
    }
    transformed_df = transformed_df.rename(columns=rename_rules)
    
    # 3. Perform mapping of Data Elements and Org Units
    transformed_df['dest_data_element'] = transformed_df['source_data_element'].map(de_mappings)
    transformed_df['dest_org_unit'] = transformed_df['source_org_unit'].map(ou_mappings)
    
    # 4. Handle Category Option Combo (COC) mapping
    default_coc_uid = coc_mappings.get('default', 'default')
    
    # If the source data has a category option combo column, try to map it
    if 'category_option_combo' in transformed_df.columns:
        transformed_df = transformed_df.rename(columns={'category_option_combo': 'source_category_option_combo'})
        # Map values; if a value is not mapped, default to the original or the default COC
        transformed_df['dest_category_option_combo'] = transformed_df['source_category_option_combo'].map(coc_mappings).fillna(default_coc_uid)
    else:
        # If not present, assign default COC UID to all rows
        transformed_df['dest_category_option_combo'] = default_coc_uid
        transformed_df['source_category_option_combo'] = None
        
    # 5. Populate destination Attribute Option Combo (AOC)
    transformed_df['dest_attribute_option_combo'] = aoc_uid
    
    # Ensure value column is kept as string since DHIS2 takes values as strings in import payload
    transformed_df['value'] = transformed_df['value'].astype(str)
    
    logger.info(
        "Transformation complete: %d rows processed. Mappings applied.",
        len(transformed_df)
    )
    
    # Re-order columns for clean visualization
    ordered_cols = [
        'source_data_element', 'dest_data_element',
        'source_org_unit', 'dest_org_unit',
        'source_category_option_combo', 'dest_category_option_combo',
        'dest_attribute_option_combo', 'period', 'value'
    ]
    
    # Ensure any extra columns in dataframe are kept
    extra_cols = [c for c in transformed_df.columns if c not in ordered_cols]
    return transformed_df[ordered_cols + extra_cols]
