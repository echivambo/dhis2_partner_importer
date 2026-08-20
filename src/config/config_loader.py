import os
import yaml
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Locate config directory relative to this script
DEFAULT_CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config"))

class ConfigLoader:
    """
    Loads global configurations. Supports persistent local_config.yaml
    and auto-generates Excel mapping template if mappings.xlsx is missing.
    """
    def __init__(self, config_dir: str = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.local_config_file = os.path.join(config_dir, "local_config.yaml")
        self.partners_file = os.path.join(config_dir, "partners.yaml")
        self.mappings_dir = os.path.join(config_dir, "mappings")
        
        self._partners_config: Dict[str, Any] = {}
        self._reports_config: Dict[str, Any] = {}
        self._sources_config: Dict[str, Any] = {}
        
        self.active_config_file = self.local_config_file
        
        self.ensure_mappings_file_exists()
        self.load_partners()

    def ensure_mappings_file_exists(self):
        """Automatically generates an empty global mappings.xlsx template (without category_option_combos)."""
        os.makedirs(self.mappings_dir, exist_ok=True)
        mapping_path = os.path.join(self.mappings_dir, "mappings.xlsx")
        
        if not os.path.exists(mapping_path):
            import pandas as pd
            logger.info("mappings.xlsx not found. Auto-generating mapping template at %s", mapping_path)
            try:
                # User requested: only data_elements and organisation_units sheets, no category_option_combos
                de_df = pd.DataFrame(columns=["Source UID", "Destination UID", "Name"])
                ou_df = pd.DataFrame(columns=["Source UID", "Destination UID", "Name", "District", "Country"])
                
                with pd.ExcelWriter(mapping_path, engine="openpyxl") as writer:
                    de_df.to_excel(writer, sheet_name="data_elements", index=False)
                    ou_df.to_excel(writer, sheet_name="organisation_units", index=False)
            except Exception as e:
                logger.error("Failed to auto-generate mappings.xlsx template: %s", e)

    def load_partners(self):
        """Load configurations from local_config.yaml (falls back to template partners.yaml)."""
        load_path = self.local_config_file
        if not os.path.exists(load_path):
            if os.path.exists(self.partners_file):
                load_path = self.partners_file
                logger.info("local_config.yaml not found. Initializing from default partners.yaml template.")
            else:
                logger.error("No configuration files found at config/ directory.")
                raise FileNotFoundError("Configuration file partners.yaml template not found.")

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self._partners_config = data.get("partners", {})
                self._reports_config = data.get("reports", {})
                self._sources_config = data.get("sources", {})
                
            logger.info(
                "Loaded configuration (%d partners, %d reports, %d sources) from %s", 
                len(self._partners_config), 
                len(self._reports_config), 
                len(self._sources_config),
                load_path
            )
            
            # Persist local copy immediately if loaded from template
            if load_path == self.partners_file:
                self.save_local_config()
        except Exception as e:
            logger.error("Error loading configuration: %s", e)
            raise

    def save_local_config(self):
        """Persists memory configurations to local_config.yaml."""
        try:
            new_yaml_config = {
                "partners": self._partners_config,
                "reports": self._reports_config,
                "sources": self._sources_config
            }
            with open(self.local_config_file, "w", encoding="utf-8") as f:
                yaml.dump(new_yaml_config, f, default_flow_style=False)
            logger.info("Successfully persisted configurations to %s", self.local_config_file)
        except Exception as e:
            logger.error("Failed to save local_config.yaml: %s", e)

    def get_partner_names(self) -> list:
        """Return list of loaded partner identifiers."""
        return list(self._partners_config.keys())

    def get_report_names(self) -> list:
        """Return list of loaded report identifiers."""
        return list(self._reports_config.keys())

    def get_reports(self) -> Dict[str, Any]:
        """Return all reports configurations."""
        return self._reports_config

    def get_sources(self) -> Dict[str, Any]:
        """Return all sources configurations."""
        return self._sources_config

    def get_partner_config(self, partner_id: str) -> Dict[str, Any]:
        """Retrieve partner configuration and load global mappings."""
        if partner_id not in self._partners_config:
            raise KeyError(f"Partner '{partner_id}' not found in configuration.")

        config = self._partners_config[partner_id].copy()

        # Load global mappings from mappings.xlsx
        mapping_file = "mappings.xlsx"
        mappings = {
            "data_elements": {},
            "organisation_units": {},
            "category_option_combos": {}
        }
        
        mapping_path = os.path.join(self.mappings_dir, mapping_file)
        if os.path.exists(mapping_path):
            mappings = self._load_excel_mappings(mapping_path)
        else:
            logger.warning("Global mapping file mappings.xlsx not found at: %s", mapping_path)

        config["mappings"] = mappings
        return config

    def _load_excel_mappings(self, path: str) -> Dict[str, Dict[str, str]]:
        import pandas as pd
        mappings = {
            "data_elements": {},
            "organisation_units": {},
            "category_option_combos": {}
        }
        try:
            with pd.ExcelFile(path) as xl:
                for sheet_name in xl.sheet_names:
                    norm_name = sheet_name.lower().strip().replace(" ", "_")
                    target_key = None
                    if "data_element" in norm_name:
                        target_key = "data_elements"
                    elif "organisation_unit" in norm_name or "org_unit" in norm_name:
                        target_key = "organisation_units"
                    elif "category_option_combo" in norm_name or "coc" in norm_name:
                        target_key = "category_option_combos"
                    
                    if target_key:
                        df = xl.parse(sheet_name)
                        if not df.empty and len(df.columns) >= 2:
                            df = df.dropna(subset=[df.columns[0], df.columns[1]])
                            for _, row in df.iterrows():
                                src = str(row.iloc[0]).strip()
                                dst = str(row.iloc[1]).strip()
                                if src and dst:
                                    mappings[target_key][src] = dst
            logger.info("Loaded Excel mappings from %s", path)
        except Exception as e:
            logger.error("Failed to load Excel mappings from %s: %s", path, e)
        return mappings

    def _load_csv_mappings(self, path: str) -> Dict[str, Dict[str, str]]:
        import pandas as pd
        mappings = {
            "data_elements": {},
            "organisation_units": {},
            "category_option_combos": {}
        }
        try:
            df = pd.read_csv(path)
            cols_clean = [str(c).lower().strip() for c in df.columns]
            
            if "type" in cols_clean:
                type_idx = cols_clean.index("type")
                src_col = None
                dst_col = None
                for i, col in enumerate(cols_clean):
                    if i == type_idx:
                        continue
                    if "source" in col or "src" in col:
                        src_col = df.columns[i]
                    elif "dest" in col or "target" in col or "dst" in col:
                        dst_col = df.columns[i]
                
                other_cols = [c for i, c in enumerate(df.columns) if i != type_idx]
                if not src_col and len(other_cols) >= 1:
                    src_col = other_cols[0]
                if not dst_col and len(other_cols) >= 2:
                    dst_col = other_cols[1]
                
                if src_col and dst_col:
                    df = df.dropna(subset=[src_col, dst_col])
                    for _, row in df.iterrows():
                        t_val = str(row[df.columns[type_idx]]).lower().strip().replace(" ", "_")
                        src = str(row[src_col]).strip()
                        dst = str(row[dst_col]).strip()
                        
                        target_key = None
                        if "data_element" in t_val or t_val == "de":
                            target_key = "data_elements"
                        elif "organisation_unit" in t_val or "org_unit" in t_val or t_val == "ou":
                            target_key = "organisation_units"
                        elif "category_option_combo" in t_val or t_val == "coc":
                            target_key = "category_option_combos"
                            
                        if target_key and src and dst:
                            mappings[target_key][src] = dst
            else:
                if len(df.columns) >= 2:
                    df = df.dropna(subset=[df.columns[0], df.columns[1]])
                    for _, row in df.iterrows():
                        src = str(row.iloc[0]).strip()
                        dst = str(row.iloc[1]).strip()
                        if src and dst:
                            mappings["data_elements"][src] = dst
            logger.info("Loaded CSV mappings from %s", path)
        except Exception as e:
            logger.error("Failed to load CSV mappings from %s: %s", path, e)
        return mappings

    def get_destination_config(self) -> Dict[str, Any]:
        """Retrieve destination instance connection credentials."""
        return {
            "url": os.getenv("DESTINATION_DHIS2_URL"),
            "username": os.getenv("DESTINATION_DHIS2_USERNAME"),
            "password": os.getenv("DESTINATION_DHIS2_PASSWORD"),
            "pat": os.getenv("DESTINATION_DHIS2_PAT"),
            "verify_ssl": os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        }
