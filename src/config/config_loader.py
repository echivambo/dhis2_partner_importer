import os
import yaml
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Locate config directory relative to this script
DEFAULT_CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config"))

class ConfigLoader:
    """
    Loads global partner settings from config/partners.yaml
    and resolves environment variables and mapping files.
    """
    def __init__(self, config_dir: str = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.partners_file = os.path.join(config_dir, "partners.yaml")
        self.mappings_dir = os.path.join(config_dir, "mappings")
        self._partners_config: Dict[str, Any] = {}
        
        self.load_partners()

    def load_partners(self):
        """Load partners configuration from partners.yaml."""
        if not os.path.exists(self.partners_file):
            logger.error("Partners config file not found: %s", self.partners_file)
            raise FileNotFoundError(f"Partners configuration file not found at {self.partners_file}")

        try:
            with open(self.partners_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self._partners_config = data.get("partners", {}) if data else {}
            logger.info("Loaded configuration for %d partners from %s", len(self._partners_config), self.partners_file)
        except Exception as e:
            logger.error("Error loading partners config: %s", e)
            raise

    def get_partner_names(self) -> list:
        """Return list of loaded partner identifiers."""
        return list(self._partners_config.keys())

    def get_partner_config(self, partner_id: str) -> Dict[str, Any]:
        """
        Retrieve partner configuration. Resolves credentials from .env and
        loads partner mapping files.
        """
        if partner_id not in self._partners_config:
            raise KeyError(f"Partner '{partner_id}' not found in configuration.")

        config = self._partners_config[partner_id].copy()
        
        # 1. Resolve source credentials from env
        source = config.get("source", {})
        resolved_source = source.copy()
        
        username_env = source.get("username_env")
        password_env = source.get("password_env")
        pat_env = source.get("pat_env")
        
        resolved_source["username"] = os.getenv(username_env) if username_env else None
        resolved_source["password"] = os.getenv(password_env) if password_env else None
        resolved_source["pat"] = os.getenv(pat_env) if pat_env else None
        
        config["source"] = resolved_source

        # 2. Load partner-specific mappings
        mapping_file = config.get("destination", {}).get("mapping_file")
        mappings = {
            "data_elements": {},
            "organisation_units": {},
            "category_option_combos": {}
        }
        
        if mapping_file:
            mapping_path = os.path.join(self.mappings_dir, mapping_file)
            if os.path.exists(mapping_path):
                try:
                    with open(mapping_path, "r", encoding="utf-8") as f:
                        map_data = yaml.safe_load(f) or {}
                        mappings["data_elements"] = map_data.get("data_elements", {})
                        mappings["organisation_units"] = map_data.get("organisation_units", {})
                        mappings["category_option_combos"] = map_data.get("category_option_combos", {})
                    logger.debug("Successfully loaded mappings from %s", mapping_path)
                except Exception as e:
                    logger.error("Failed to parse mapping file %s: %s", mapping_path, e)
            else:
                logger.warning("Mapping file configured but not found: %s", mapping_path)

        config["mappings"] = mappings
        return config

    def get_destination_config(self) -> Dict[str, Any]:
        """Retrieve destination instance connection credentials from global environment."""
        return {
            "url": os.getenv("DESTINATION_DHIS2_URL"),
            "username": os.getenv("DESTINATION_DHIS2_USERNAME"),
            "password": os.getenv("DESTINATION_DHIS2_PASSWORD"),
            "pat": os.getenv("DESTINATION_DHIS2_PAT"),
            "verify_ssl": os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        }
