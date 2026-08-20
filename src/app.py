"""
DHIS2 Partner Importer - Standalone Web Application Backend

This module implements the FastAPI backend for the standalone web application.
It exposes REST endpoints for:
1. Fetching partner configurations and running health checks on connections.
2. Managing the ETL pipeline (extracting, transforming/validating, running dry run, and importing).
3. Downloading and uploading Excel/CSV mapping configurations.
4. Managing application settings (.env credentials and partners/reports yaml config) dynamically.

Run locally using:
    uvicorn src.app:app --port 8005 --reload
"""

import os
import sys
import logging
import shutil
import yaml
import pandas as pd
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config.config_loader import ConfigLoader
from src.dhis2.client import DHIS2Client, DHIS2Error
from src.dhis2.analytics import extract_partner_data
from src.transformation.transformer import transform_partner_data
from src.validation.validator import validate_transformed_data
from src.dhis2.importer import import_to_dhis2

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title="DISC DHIS2 Data Importer Backend",
    description="Backend API for managing DHIS2 integration, credentials, and data pipeline.",
    version="2.0.0"
)

# Global variables for caching active dataframes and configs
# Key: partner_id, Value: dict containing 'raw_df', 'transformed_df', 'validation_report'
active_state: Dict[str, Dict[str, Any]] = {}

def get_config_loader() -> ConfigLoader:
    """Instantiates and returns the ConfigLoader pointing to the config directory."""
    config_dir = os.path.join(PROJECT_ROOT, "config")
    # Reload environment variables before loading configs to ensure changes are reflected
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
    return ConfigLoader(config_dir=config_dir)

# --- REQUEST AND RESPONSE MODELS ---

class ExtractRequest(BaseModel):
    partner_id: str
    report_id: str
    year: str
    month: str

class ValidateRequest(BaseModel):
    partner_id: str

class DryRunRequest(BaseModel):
    partner_id: str
    ignore_missing_mappings: bool = False

class ImportRequest(BaseModel):
    partner_id: str
    ignore_missing_mappings: bool = False
    mark_as_complete: bool = False

class SettingsUpdate(BaseModel):
    destination_url: str
    destination_username: str
    destination_password: str
    destination_pat: Optional[str] = ""
    verify_ssl: bool = True
    partners: Dict[str, Dict[str, Any]]  # Key: partner ID, Value: partner data
    reports: Dict[str, Dict[str, Any]]   # Key: report ID, Value: report data

# --- CORE ENDPOINTS ---

@app.get("/api/partners")
def list_partners():
    """Retrieves a list of all configured partner IDs and metadata, along with available reports."""
    try:
        loader = get_config_loader()
        
        # Build partners map
        partners_data = {}
        for name in loader.get_partner_names():
            config = loader._partners_config.get(name, {})
            partners_data[name] = {
                "name": config.get("name"),
                "attribute_option_combo": config.get("attribute_option_combo"),
                "data_set": config.get("data_set"),
                "mapping_file": config.get("mapping_file")
            }
            
        # Build reports map
        reports_data = {}
        for name, r_config in loader.get_reports().items():
            reports_data[name] = {
                "name": r_config.get("name"),
                "pivot_table_url": r_config.get("pivot_table_url")
            }
            
        return {
            "status": "success",
            "partners": partners_data,
            "reports": reports_data
        }
    except Exception as e:
        logger.error("Failed to retrieve partners and reports: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
def run_health_checks():
    """Runs connectivity checks on the target destination DHIS2 and all partner report base URLs."""
    try:
        loader = get_config_loader()
        dest = loader.get_destination_config()
        
        # 1. Check destination connection
        dest_status = {"status": "Disconnected", "version": "N/A", "error": None}
        if dest.get("url"):
            try:
                dest_client = DHIS2Client(
                    base_url=dest["url"],
                    username=dest.get("username"),
                    password=dest.get("password"),
                    pat=dest.get("pat"),
                    verify_ssl=dest.get("verify_ssl", True),
                    timeout=5.0
                )
                res = dest_client.get("api/system/info")
                data = res.json()
                dest_status = {"status": "Connected", "version": data.get("version", "Unknown"), "error": None}
            except Exception as e:
                dest_status["error"] = str(e)
        else:
            dest_status["error"] = "No destination URL configured."

        # 2. Check connections to reports base URLs
        report_statuses = {}
        for report_id, r_config in loader.get_reports().items():
            report_statuses[report_id] = {"status": "Disconnected", "version": "N/A", "error": None}
            url = r_config.get("pivot_table_url", "")
            
            if url:
                try:
                    parsed = urlparse(url)
                    base_url = f"{parsed.scheme}://{parsed.netloc}"
                    
                    src_client = DHIS2Client(
                        base_url=base_url,
                        username=r_config.get("username"),
                        password=r_config.get("password"),
                        verify_ssl=os.getenv("VERIFY_SSL", "true").lower() in ("true", "1"),
                        timeout=5.0
                    )
                    res = src_client.get("api/system/info")
                    data = res.json()
                    report_statuses[report_id] = {"status": "Connected", "version": data.get("version", "Unknown"), "error": None}
                except Exception as e:
                    report_statuses[report_id]["error"] = str(e)
            else:
                report_statuses[report_id]["error"] = "No Pivot Table URL configured."
                
        return {
            "status": "success",
            "destination": dest_status,
            "reports": report_statuses
        }
    except Exception as e:
        logger.error("Failed running connection health checks: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/extract")
def extract_data(request: ExtractRequest):
    """Executes the extraction process from the source report's DHIS2 pivot table URL for a combined YYYYMM period."""
    partner_id = request.partner_id
    report_id = request.report_id
    period = f"{request.year}{request.month}"
    
    logger.info("Extracting data for partner=%s, report=%s, period=%s", partner_id, report_id, period)
    try:
        loader = get_config_loader()
        
        # 1. Fetch Report credentials and pivot URL
        reports = loader.get_reports()
        if report_id not in reports:
            raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found in configuration.")
            
        r_config = reports[report_id]
        pivot_table_url = r_config.get("pivot_table_url", "")
        if not pivot_table_url:
            raise HTTPException(status_code=400, detail="Pivot table URL is missing in the report configuration.")
            
        # Parse base URL from pivot URL
        parsed = urlparse(pivot_table_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Instantiate client
        client = DHIS2Client(
            base_url=base_url,
            username=r_config.get("username"),
            password=r_config.get("password"),
            verify_ssl=os.getenv("VERIFY_SSL", "true").lower() in ("true", "1")
        )
        
        # Pull raw csv from Analytics
        raw_df = extract_partner_data(client, pivot_table_url, period)
        
        # 2. Fetch Partner mapping and destination settings
        partner_config = loader.get_partner_config(partner_id)
        
        # Store state in memory
        active_state[partner_id] = {
            "raw_df": raw_df,
            "transformed_df": None,
            "validation_report": None,
            "period": period,
            "partner_config": partner_config
        }
        
        unique_de = raw_df['data_element'].nunique() if not raw_df.empty else 0
        unique_ou = raw_df['org_unit'].nunique() if not raw_df.empty else 0
        
        return {
            "status": "success",
            "records_extracted": len(raw_df),
            "unique_org_units": unique_ou,
            "unique_data_elements": unique_de
        }
    except Exception as e:
        logger.error("Extraction failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

@app.post("/api/validate")
def validate_data(request: ValidateRequest):
    """Runs data mappings translation and performs validation constraints on UIDs."""
    partner_id = request.partner_id
    
    if partner_id not in active_state or active_state[partner_id]["raw_df"] is None:
        raise HTTPException(status_code=400, detail="Data must be extracted before running validation.")
        
    state = active_state[partner_id]
    
    try:
        # 1. Run Mappings Transformation
        transformed_df = transform_partner_data(state["raw_df"], state["partner_config"])
        state["transformed_df"] = transformed_df
        
        # 2. Run Mappings Validation
        report = validate_transformed_data(transformed_df, state["partner_config"])
        state["validation_report"] = report
        
        summary = report.summary()
        
        # Generate missing template file automatically in the background if validation failed
        has_missing = len(report.missing_data_elements) > 0 or len(report.missing_organisation_units) > 0
        if has_missing:
            generate_template_with_missing_keys(partner_id, state)
            
        # Compile a data preview to render in the UI table (limit 15 rows)
        preview_data = []
        if not transformed_df.empty:
            preview_cols = [
                'source_data_element', 'dest_data_element',
                'source_org_unit', 'dest_org_unit',
                'value'
            ]
            preview_data = transformed_df[preview_cols].head(15).fillna("").to_dict(orient="records")
            
        return {
            "status": "success",
            "is_valid": summary["is_valid"],
            "missing_de_count": summary["missing_de_count"],
            "missing_de_list": summary["missing_de_list"],
            "missing_ou_count": summary["missing_ou_count"],
            "missing_ou_list": summary["missing_ou_list"],
            "invalid_periods_count": summary["invalid_periods_count"],
            "invalid_periods_list": summary["invalid_periods_list"],
            "empty_values_count": summary["empty_values_count"],
            "errors": summary["errors"],
            "preview": preview_data,
            "has_missing_mappings": has_missing
        }
    except Exception as e:
        logger.error("Validation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")

@app.post("/api/dry-run")
def dry_run_import(request: DryRunRequest):
    """Performs a simulated dry-run import to the target DHIS2 server."""
    partner_id = request.partner_id
    ignore_missing = request.ignore_missing_mappings
    
    if partner_id not in active_state or active_state[partner_id]["transformed_df"] is None:
        raise HTTPException(status_code=400, detail="Data must be extracted and validated before running Dry Run.")
        
    state = active_state[partner_id]
    
    try:
        loader = get_config_loader()
        dest = loader.get_destination_config()
        dest_client = DHIS2Client(
            base_url=dest["url"],
            username=dest.get("username"),
            password=dest.get("password"),
            pat=dest.get("pat"),
            verify_ssl=dest.get("verify_ssl", True)
        )
        
        # Extract direct AOC from partner config or fall back to nested
        partner_config = state["partner_config"]
        # Overwrite destination attribute option combo in partner config for import processor
        if "attribute_option_combo" in partner_config:
            if "destination" not in partner_config:
                partner_config["destination"] = {}
            partner_config["destination"]["attribute_option_combo"] = partner_config["attribute_option_combo"]
            partner_config["destination"]["data_set"] = partner_config.get("data_set", "")

        res = import_to_dhis2(
            dest_client=dest_client,
            transformed_df=state["transformed_df"],
            partner_config=partner_config,
            dry_run=True,
            ignore_missing_mappings=ignore_missing
        )
        
        return {
            "status": "success",
            "import_status": res.get("status"),
            "records_extracted": res.get("records_extracted"),
            "records_transformed": res.get("records_transformed"),
            "will_mark_complete": res.get("will_mark_complete"),
            "message": res.get("message", "")
        }
    except Exception as e:
        logger.error("Dry run failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Dry Run failed: {str(e)}")

@app.post("/api/import")
def live_import(request: ImportRequest):
    """Performs the live import to write records to the target DHIS2 server."""
    partner_id = request.partner_id
    ignore_missing = request.ignore_missing_mappings
    mark_complete = request.mark_as_complete
    
    if partner_id not in active_state or active_state[partner_id]["transformed_df"] is None:
        raise HTTPException(status_code=400, detail="Data must be extracted and validated before running Import.")
        
    state = active_state[partner_id]
    
    try:
        loader = get_config_loader()
        dest = loader.get_destination_config()
        dest_client = DHIS2Client(
            base_url=dest["url"],
            username=dest.get("username"),
            password=dest.get("password"),
            pat=dest.get("pat"),
            verify_ssl=dest.get("verify_ssl", True)
        )
        
        partner_config = state["partner_config"]
        # Align direct config attributes to target importer fields
        if "attribute_option_combo" in partner_config:
            if "destination" not in partner_config:
                partner_config["destination"] = {}
            partner_config["destination"]["attribute_option_combo"] = partner_config["attribute_option_combo"]
            partner_config["destination"]["data_set"] = partner_config.get("data_set", "")

        res = import_to_dhis2(
            dest_client=dest_client,
            transformed_df=state["transformed_df"],
            partner_config=partner_config,
            dry_run=False,
            ignore_missing_mappings=ignore_missing,
            mark_as_complete=mark_complete
        )
        
        return {
            "status": "success",
            "import_status": res.get("status"),
            "message": res.get("message"),
            "import_count": res.get("import_count", {}),
            "completion_report": res.get("completion_report", {}),
            "conflicts": res.get("conflicts", [])
        }
    except Exception as e:
        logger.error("Import failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

# --- CONFIGURATIONS AND SETTINGS ENDPOINTS ---

@app.get("/api/settings")
def get_settings():
    """Reads current credentials and system variables from the local .env and partners.yaml files securely."""
    try:
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
        loader = get_config_loader()
        
        settings = {
            "destination_url": os.getenv("DESTINATION_DHIS2_URL") or "",
            "destination_username": os.getenv("DESTINATION_DHIS2_USERNAME") or "",
            "destination_password": os.getenv("DESTINATION_DHIS2_PASSWORD") or "",
            "destination_pat": os.getenv("DESTINATION_DHIS2_PAT") or "",
            "verify_ssl": (os.getenv("VERIFY_SSL") or "true").lower() in ("true", "1", "yes"),
            "partners": loader._partners_config,
            "reports": loader._reports_config
        }
        return {"status": "success", "settings": settings}
    except Exception as e:
        logger.error("Failed to read settings: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings")
def update_settings(settings: SettingsUpdate):
    """Saves updated credentials to .env and updates partners and reports inside partners.yaml."""
    try:
        # 1. Update destination in .env
        env_dict = {
            "DESTINATION_DHIS2_URL": settings.destination_url,
            "DESTINATION_DHIS2_USERNAME": settings.destination_username,
            "DESTINATION_DHIS2_PASSWORD": settings.destination_password,
            "DESTINATION_DHIS2_PAT": settings.destination_pat or "",
            "VERIFY_SSL": "true" if settings.verify_ssl else "false"
        }
        save_env_variables(env_dict)
        
        # 2. Update partners and reports in partners.yaml
        loader = get_config_loader()
        new_yaml_config = {
            "partners": settings.partners,
            "reports": settings.reports
        }
        with open(loader.partners_file, "w", encoding="utf-8") as f:
            yaml.dump(new_yaml_config, f, default_flow_style=False)
            
        logger.info("Saved settings and YAML updates to partners.yaml.")
        return {"status": "success", "message": "Settings updated successfully."}
    except Exception as e:
        logger.error("Failed to save settings: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# --- MAPPINGS MANAGEMENT ENDPOINTS ---

@app.post("/api/mapping/upload")
async def upload_mapping_file(partner_id: str = Form(...), file: UploadFile = File(...)):
    """Handles Excel/CSV mapping uploads. Saves files and updates configs dynamically."""
    try:
        loader = get_config_loader()
        partner_config = loader.get_partner_config(partner_id)
        target_mapping_file = partner_config.get("mapping_file") or partner_config.get("destination", {}).get("mapping_file")
        
        if not target_mapping_file:
            raise HTTPException(status_code=400, detail="No mapping file configured for selected partner.")
            
        filename = file.filename
        ext_uploaded = os.path.splitext(filename)[1].lower()
        ext_configured = os.path.splitext(target_mapping_file)[1].lower()
        
        # Resolve target path
        if ext_uploaded != ext_configured:
            # Update partners.yaml reference if extension changed
            base_name = os.path.splitext(target_mapping_file)[0]
            new_mapping_file = base_name + ext_uploaded
            target_path = os.path.join(loader.mappings_dir, new_mapping_file)
            
            # Write to partners.yaml
            loader._partners_config[partner_id]["mapping_file"] = new_mapping_file
            with open(loader.partners_file, "w", encoding="utf-8") as f:
                yaml.dump({
                    "partners": loader._partners_config,
                    "reports": loader._reports_config
                }, f, default_flow_style=False)
            logger.info("Updated partners.yaml mapping_file reference to %s", new_mapping_file)
            target_mapping_file = new_mapping_file
        else:
            target_path = os.path.join(loader.mappings_dir, target_mapping_file)
            
        # Save content
        with open(target_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        logger.info("Mapping file '%s' uploaded and written to %s", filename, target_path)
        
        # Clear cached transform state to force re-evaluation
        if partner_id in active_state:
            active_state[partner_id]["transformed_df"] = None
            active_state[partner_id]["validation_report"] = None
            active_state[partner_id]["partner_config"] = get_config_loader().get_partner_config(partner_id)
            
        return {"status": "success", "message": f"Mapping file '{filename}' successfully updated."}
    except Exception as e:
        logger.error("Failed to upload mapping file: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/mapping/download/{partner_id}")
def download_mapping_file(partner_id: str):
    """Serves the active Excel/CSV mapping file for editing."""
    try:
        loader = get_config_loader()
        partner_config = loader.get_partner_config(partner_id)
        target_mapping_file = partner_config.get("mapping_file") or partner_config.get("destination", {}).get("mapping_file")
        
        if not target_mapping_file:
            raise HTTPException(status_code=404, detail="Mapping file not found for selected partner.")
            
        target_path = os.path.join(loader.mappings_dir, target_mapping_file)
        if not os.path.exists(target_path):
            raise HTTPException(status_code=404, detail="Configuration mapping file does not exist on disk.")
            
        return FileResponse(
            path=target_path,
            filename=target_mapping_file,
            media_type="application/octet-stream"
        )
    except Exception as e:
        logger.error("Failed downloading mapping: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# --- HELPER UTILITIES ---

def save_env_variables(vars_dict: dict):
    """Updates key-value credentials in the project-level .env file."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    updated_keys = set()
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip()
            if key in vars_dict:
                new_lines.append(f"{key}={vars_dict[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)
        
    for key, val in vars_dict.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")
            
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    logger.info("Saved credentials to .env")

def generate_template_with_missing_keys(partner_id: str, state: dict):
    """Generates an Excel/CSV mapping template pre-populated with Name, District, and County columns for Org Units."""
    try:
        loader = get_config_loader()
        partner_config = state["partner_config"]
        mapping_file = partner_config.get("mapping_file") or partner_config.get("destination", {}).get("mapping_file")
        if not mapping_file:
            return
            
        mapping_path = os.path.join(loader.mappings_dir, mapping_file)
        report = state["validation_report"]
        
        current_de_map = partner_config["mappings"].get("data_elements", {})
        current_ou_map = partner_config["mappings"].get("organisation_units", {})
        current_coc_map = partner_config["mappings"].get("category_option_combos", {})
        
        # Compile unique Data Elements rows
        de_rows = [{"Source UID": src, "Destination UID": dst} for src, dst in current_de_map.items()]
        for src in report.missing_data_elements:
            if src not in current_de_map:
                de_rows.append({"Source UID": src, "Destination UID": ""})
                
        # Read existing Excel mapping file to preserve existing descriptions (name, district, county) if it is xlsx
        existing_ou_details = {}
        ext = os.path.splitext(mapping_file)[1].lower()
        
        if ext in (".xlsx", ".xls") and os.path.exists(mapping_path):
            try:
                with pd.ExcelFile(mapping_path) as xl:
                    sheet_names_clean = [s.lower().strip().replace(" ", "_") for s in xl.sheet_names]
                    if "organisation_units" in sheet_names_clean:
                        idx = sheet_names_clean.index("organisation_units")
                        sheet_name = xl.sheet_names[idx]
                        existing_df = xl.parse(sheet_name)
                        if not existing_df.empty and len(existing_df.columns) >= 2:
                            for _, row in existing_df.iterrows():
                                src_val = str(row.iloc[0]).strip()
                                name_val = str(row.iloc[2]).strip() if len(row) > 2 and not pd.isna(row.iloc[2]) else ""
                                dist_val = str(row.iloc[3]).strip() if len(row) > 3 and not pd.isna(row.iloc[3]) else ""
                                cty_val = str(row.iloc[4]).strip() if len(row) > 4 and not pd.isna(row.iloc[4]) else ""
                                existing_ou_details[src_val] = {
                                    "Name": name_val,
                                    "District": dist_val,
                                    "County": cty_val
                                }
            except Exception as e:
                logger.warning("Could not parse existing organization unit details: %s", e)

        # Compile unique Organisation Units rows with extra columns
        ou_rows = []
        for src, dst in current_ou_map.items():
            details = existing_ou_details.get(src, {"Name": "", "District": "", "County": ""})
            ou_rows.append({
                "Source UID": src,
                "Destination UID": dst,
                "Name": details["Name"],
                "District": details["District"],
                "County": details["County"]
            })
        for src in report.missing_organisation_units:
            if src not in current_ou_map:
                ou_rows.append({
                    "Source UID": src,
                    "Destination UID": "",
                    "Name": "",
                    "District": "",
                    "County": ""
                })
                
        coc_rows = [{"Source UID": src, "Destination UID": dst} for src, dst in current_coc_map.items()]
        if not coc_rows:
            coc_rows.append({"Source UID": "default", "Destination UID": "DEFAULT_COC_UID"})
            
        if ext in (".xlsx", ".xls"):
            with pd.ExcelWriter(mapping_path, engine="openpyxl") as writer:
                pd.DataFrame(de_rows).to_excel(writer, sheet_name="data_elements", index=False)
                pd.DataFrame(ou_rows).to_excel(writer, sheet_name="organisation_units", index=False)
                pd.DataFrame(coc_rows).to_excel(writer, sheet_name="category_option_combos", index=False)
            logger.info("Auto-generated missing mappings template Excel at %s", mapping_path)
        elif ext == ".csv":
            rows = []
            for r in de_rows:
                rows.append({"type": "data_element", "source": r["Source UID"], "destination": r["Destination UID"]})
            for r in ou_rows:
                # Flat structure for CSV format
                rows.append({
                    "type": "organisation_unit", 
                    "source": r["Source UID"], 
                    "destination": r["Destination UID"]
                })
            for r in coc_rows:
                rows.append({"type": "category_option_combo", "source": r["Source UID"], "destination": r["Destination UID"]})
            pd.DataFrame(rows).to_csv(mapping_path, index=False)
            logger.info("Auto-generated missing mappings template CSV at %s", mapping_path)
    except Exception as e:
        logger.error("Background template generation failed: %s", e)

# Serve single-page app HTML
@app.get("/")
def get_index():
    """Serves the main single-page application dashboard interface."""
    static_index = os.path.join(PROJECT_ROOT, "src", "web", "index.html")
    if os.path.exists(static_index):
        return FileResponse(static_index)
    else:
        return JSONResponse(status_code=404, content={"message": "Frontend assets not found. Run setup tasks."})

# Mount the static assets directory under /static
web_dir = os.path.join(PROJECT_ROOT, "src", "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")
