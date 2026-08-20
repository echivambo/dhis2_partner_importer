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
    def map_de_row(source_de_str):
        if pd.isna(source_de_str) or not isinstance(source_de_str, str):
            return None, None, None
            
        source_de_str = source_de_str.strip()
        
        # Try exact match first
        mapped = de_mappings.get(source_de_str)
        
        # Parse source DE and COC
        src_de = source_de_str
        src_coc = None
        if "." in source_de_str:
            src_de, src_coc = source_de_str.split(".", 1)
            
        if not mapped:
            # Match DE part only
            mapped = de_mappings.get(src_de)
            
        if mapped:
            mapped = str(mapped).strip()
            if "." in mapped:
                dest_de, dest_coc = mapped.split(".", 1)
                return dest_de, src_coc, dest_coc
            else:
                return mapped, src_coc, "default"
        else:
            return None, src_coc, None

    # Apply mapping row-by-row
    mapped_results = transformed_df['source_data_element'].apply(map_de_row)
    
    transformed_df['dest_data_element'] = [res[0] for res in mapped_results]
    transformed_df['source_category_option_combo'] = [res[1] for res in mapped_results]
    transformed_df['dest_category_option_combo'] = [res[2] for res in mapped_results]
    
    transformed_df['dest_org_unit'] = transformed_df['source_org_unit'].map(ou_mappings)

        
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
