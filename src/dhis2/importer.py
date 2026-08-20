import logging
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from src.dhis2.client import DHIS2Client
from src.validation.validator import validate_transformed_data, ValidationReport

logger = logging.getLogger(__name__)

def create_data_value_set_payload(
    df: pd.DataFrame,
    dataset_uid: str,
    default_aoc_uid: str
) -> Dict[str, Any]:
    """
    Converts the transformed DataFrame to a DHIS2 Data Value Set JSON structure.
    Only rows with valid destination UIDs are included.
    """
    data_values = []
    
    for _, row in df.iterrows():
        dest_de = row.get('dest_data_element')
        dest_ou = row.get('dest_org_unit')
        val = row.get('value')
        pe = row.get('period')
        
        # Skip records without valid destination mapping UIDs
        if pd.isna(dest_de) or pd.isna(dest_ou) or dest_de == '' or dest_ou == '':
            continue
            
        coc = row.get('dest_category_option_combo')
        aoc = row.get('dest_attribute_option_combo', default_aoc_uid)
        
        data_value = {
            "dataElement": str(dest_de),
            "period": str(pe),
            "orgUnit": str(dest_ou),
            "value": str(val)
        }
        
        if coc and not pd.isna(coc) and coc != '':
            data_value["categoryOptionCombo"] = str(coc)
            
        if aoc and not pd.isna(aoc) and aoc != '':
            data_value["attributeOptionCombo"] = str(aoc)
            
        data_values.append(data_value)

    # Use today's date for completeness registration stamp
    today_str = datetime.date.today().isoformat()
    
    payload = {
        "dataSet": dataset_uid,
        "completeDate": today_str,
        "dataValues": data_values
    }
    
    return payload


def complete_dataset_for_partner(
    dest_client: DHIS2Client,
    dataset_uid: str,
    period: str,
    org_unit_uids: List[str],
    aoc_uid: str
) -> Dict[str, Any]:
    """
    Registers the dataset as complete on the destination DHIS2 server for the specified org units.
    Uses the /api/completeDataSetRegistrations endpoint.
    """
    registrations = []
    for ou in org_unit_uids:
        registrations.append({
            "dataSet": dataset_uid,
            "period": period,
            "organisationUnit": ou,
            "attributeOptionCombo": aoc_uid
        })
        
    payload = {
        "completeDataSetRegistrations": registrations
    }
    
    logger.info("Registering DataSet completion for %d Organisation Units...", len(org_unit_uids))
    try:
        response = dest_client.post("api/completeDataSetRegistrations", json=payload)
        # Note: completeDataSetRegistrations endpoint returns 204 No Content on success, or a summary.
        # Check if response has body content
        res_json = response.json() if (response.text and response.text.strip()) else {}
        logger.info("Successfully registered DataSet completion.")
        return {
            "status": "SUCCESS",
            "message": "DataSet registration marked complete.",
            "response": res_json
        }
    except Exception as e:
        logger.error("Failed to mark DataSet as complete: %s", e)
        return {
            "status": "ERROR",
            "message": f"Failed to mark DataSet as complete: {str(e)}"
        }


def import_to_dhis2(
    dest_client: DHIS2Client,
    transformed_df: pd.DataFrame,
    partner_config: Dict[str, Any],
    dry_run: bool = False,
    ignore_missing_mappings: bool = False,
    mark_as_complete: bool = False
) -> Dict[str, Any]:
    """
    Validates, transforms, and imports data to the destination DHIS2 instance.
    If dry_run is True, returns an import execution summary without posting.
    Optional: Marks the dataset as complete upon successful import.
    """
    partner_name = partner_config.get("name", "Unknown Partner")
    dest_config = partner_config.get("destination", {})
    dataset_uid = dest_config.get("data_set")
    aoc_uid = dest_config.get("attribute_option_combo")

    # 1. Run validations
    report = validate_transformed_data(transformed_df, partner_config)
    
    # Check if there are blocking issues
    if not report.is_valid and not ignore_missing_mappings:
        logger.error("Import blocked due to validation failures.")
        return {
            "status": "BLOCKED",
            "message": "Import blocked by validation rules. Review missing mappings.",
            "validation_report": report.summary()
        }

    # Count records that have valid mappings
    total_records = len(transformed_df)
    valid_mappings_df = transformed_df[
        transformed_df['dest_data_element'].notna() & (transformed_df['dest_data_element'] != '') &
        transformed_df['dest_org_unit'].notna() & (transformed_df['dest_org_unit'] != '')
    ]
    records_to_import = len(valid_mappings_df)

    # Generate payload
    payload = create_data_value_set_payload(transformed_df, dataset_uid, aoc_uid)

    # 2. Dry Run Simulation Mode
    if dry_run:
        logger.info("Executing DRY RUN for partner: %s", partner_name)
        return {
            "status": "DRY_RUN_SUCCESS",
            "message": "Dry run execution completed. Verify configuration.",
            "records_extracted": total_records,
            "records_transformed": records_to_import,
            "validation_report": report.summary(),
            "payload_preview": {
                "dataSet": payload["dataSet"],
                "dataValuesCount": len(payload["dataValues"]),
                "sampleValues": payload["dataValues"][:5] # returns a small sample
            },
            "will_mark_complete": mark_as_complete
        }

    # 3. Live Mode Execution
    logger.info("Starting live import to DHIS2 for partner: %s", partner_name)
    try:
        import json
        from src.dhis2.client import DHIS2HTTPError
        
        try:
            response = dest_client.post("api/dataValueSets", json=payload)
            import_summary = response.json()
        except DHIS2HTTPError as e:
            if e.status_code == 409 and e.response_text:
                try:
                    import_summary = json.loads(e.response_text)
                except Exception:
                    raise e
            else:
                raise e
        
        # Handle cases where DHIS2 wraps the summary in a "response" key
        if "response" in import_summary and isinstance(import_summary["response"], dict):
            import_summary = import_summary["response"]
            
        status = import_summary.get("status", "SUCCESS")
        import_count = import_summary.get("importCount", {})
        conflicts = import_summary.get("conflicts", [])
        
        logger.info(
            "Import completed. Status: %s. Imported: %s, Updated: %s, Ignored: %s, Conflicts: %d",
            status,
            import_count.get("imported", 0),
            import_count.get("updated", 0),
            import_count.get("ignored", 0),
            len(conflicts)
        )
        
        # 4. Mark DataSet complete if requested and import succeeded
        completion_report = None
        if mark_as_complete and status in ("SUCCESS", "WARNING") and payload["dataValues"]:
            # Extract unique organisation units and period from payload values
            unique_org_units = list({val["orgUnit"] for val in payload["dataValues"] if "orgUnit" in val})
            unique_periods = list({val["period"] for val in payload["dataValues"] if "period" in val})
            
            if unique_org_units and unique_periods:
                completion_report = complete_dataset_for_partner(
                    dest_client=dest_client,
                    dataset_uid=dataset_uid,
                    period=unique_periods[0],
                    org_unit_uids=unique_org_units,
                    aoc_uid=aoc_uid
                )
        
        result = {
            "status": status,
            "message": "Data successfully sent to destination server.",
            "total_records": len(payload["dataValues"]),
            "import_count": import_count,
            "conflicts": conflicts,
            "validation_report": report.summary()
        }
        if completion_report:
            result["completion_report"] = completion_report
            
        return result
        
    except Exception as e:
        logger.exception("Failed to import dataset to DHIS2 target.")
        return {
            "status": "ERROR",
            "message": f"Network or API Error occurred: {str(e)}",
            "validation_report": report.summary()
        }
