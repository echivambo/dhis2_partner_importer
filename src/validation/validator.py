import re
import logging
import pandas as pd
from typing import Dict, Any, List, Set, Optional

logger = logging.getLogger(__name__)

class ValidationReport:
    """
    Represents the output of the data validation process.
    Stores missing mappings, invalid entries, and flags critical status.
    """
    def __init__(self):
        self.missing_data_elements: Set[str] = set()
        self.missing_organisation_units: Set[str] = set()
        self.invalid_periods: Set[str] = set()
        self.empty_values_count: int = 0
        self.errors: List[str] = []

    @property
    def is_valid(self) -> bool:
        """
        Returns True if there are no critical errors blocking the import.
        Missing mappings or invalid periods are considered critical blockages.
        """
        return (
            len(self.missing_data_elements) == 0 and
            len(self.missing_organisation_units) == 0 and
            len(self.invalid_periods) == 0 and
            len(self.errors) == 0
        )

    def summary(self) -> Dict[str, Any]:
        """Returns a summarized dictionary of findings."""
        return {
            "is_valid": self.is_valid,
            "missing_de_count": len(self.missing_data_elements),
            "missing_de_list": list(self.missing_data_elements),
            "missing_ou_count": len(self.missing_organisation_units),
            "missing_ou_list": list(self.missing_organisation_units),
            "invalid_periods_count": len(self.invalid_periods),
            "invalid_periods_list": list(self.invalid_periods),
            "empty_values_count": self.empty_values_count,
            "errors": self.errors
        }


def validate_transformed_data(df: pd.DataFrame, partner_config: Dict[str, Any]) -> ValidationReport:
    """
    Validates a transformed DataFrame before importing into the destination instance.
    Checks for missing mappings, empty values, invalid periods, and config completeness.
    """
    report = ValidationReport()
    partner_name = partner_config.get("name", "Unknown Partner")
    logger.info("Validating transformed data for partner: %s", partner_name)

    # 1. Validate Partner Configuration attributes
    dest_config = partner_config.get("destination", {})
    dataset_uid = dest_config.get("data_set")
    aoc_uid = dest_config.get("attribute_option_combo")

    if not dataset_uid:
        report.errors.append("Destination dataset ID (data_set) is missing in configuration.")
    if not aoc_uid:
        report.errors.append("Destination Attribute Option Combo ID (attribute_option_combo) is missing in configuration.")

    if df.empty:
        report.errors.append("The dataset is empty. Nothing to import.")
        return report

    # 2. Check for missing mappings
    # Find rows where destination DE UID is null or empty
    missing_de_df = df[df['dest_data_element'].isna() | (df['dest_data_element'] == '')]
    if not missing_de_df.empty:
        report.missing_data_elements = set(missing_de_df['source_data_element'].unique())
        logger.warning("Found %d rows with missing Data Element mappings.", len(missing_de_df))

    # Find rows where destination OU UID is null or empty
    missing_ou_df = df[df['dest_org_unit'].isna() | (df['dest_org_unit'] == '')]
    if not missing_ou_df.empty:
        report.missing_organisation_units = set(missing_ou_df['source_org_unit'].unique())
        logger.warning("Found %d rows with missing Organisation Unit mappings.", len(missing_ou_df))

    # 3. Validate values and periods
    period_pattern = re.compile(r"^\d{6}$") # YYYYMM format
    
    for idx, row in df.iterrows():
        # Check value completeness
        val = str(row['value']).strip()
        if not val or val.lower() in ('nan', 'none', 'null', ''):
            report.empty_values_count += 1
            
        # Check period layout (must be 6 digits, e.g. 202601)
        pe = str(row['period']).strip()
        if not period_pattern.match(pe):
            report.invalid_periods.add(pe)
            
    if report.invalid_periods:
        logger.warning("Found invalid DHIS2 periods: %s", report.invalid_periods)

    if report.empty_values_count > 0:
        logger.warning("Found %d rows with empty values.", report.empty_values_count)

    logger.info(
        "Validation completed. Safe to import: %s. Errors found: %d. Missing mappings: DEs=%d, OUs=%d",
        report.is_valid,
        len(report.errors),
        len(report.missing_data_elements),
        len(report.missing_organisation_units)
    )

    return report
