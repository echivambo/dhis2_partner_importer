import os
import logging
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, HTML, clear_output
from dotenv import load_dotenv

from src.config.config_loader import ConfigLoader
from src.utils.periods import generate_readable_periods, to_human_period
from src.dhis2.client import DHIS2Client
from src.dhis2.analytics import extract_partner_data
from src.transformation.transformer import transform_partner_data
from src.validation.validator import validate_transformed_data
from src.dhis2.importer import import_to_dhis2
from src.utils.logging import setup_logging, scrub_sensitive_data

# Ensure logs are set up
setup_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env vars
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env")))

class ImporterDashboard:
    def __init__(self):
        # 1. Config Loader
        config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config"))
        self.loader = ConfigLoader(config_dir=config_dir)
        
        # 2. State management
        self.current_partner_id = None
        self.current_partner_config = None
        self.current_period_val = None
        self.raw_df = None
        self.transformed_df = None
        self.validation_report = None
        
        # 3. Widgets Definition
        self.title_label = widgets.HTML(
            value="<h1 style='color:#0078d4; font-family:sans-serif;'>DISC DHIS2 DATA IMPORTER</h1>"
        )
        
        # Partner Selector
        partner_names = self.loader.get_partner_names()
        self.partner_select = widgets.Dropdown(
            options=partner_names,
            value=partner_names[0] if partner_names else None,
            description='Partner:',
            style={'description_width': 'initial'},
            layout=widgets.Layout(width='350px')
        )
        
        # Period Selector
        periods = generate_readable_periods(years_back=2)
        self.period_select = widgets.Dropdown(
            options=periods,
            value=periods[0][1] if periods else None,
            description='Period:',
            style={'description_width': 'initial'},
            layout=widgets.Layout(width='350px')
        )
        
        # Action Buttons
        self.btn_extract = widgets.Button(
            description='EXTRACT DATA',
            button_style='info', # 'success', 'info', 'warning', 'danger' or ''
            layout=widgets.Layout(width='180px', margin='10px 0px')
        )
        self.btn_validate = widgets.Button(
            description='VALIDATE MAPPINGS',
            button_style='warning',
            layout=widgets.Layout(width='180px', margin='10px 0px'),
            disabled=True
        )
        self.btn_dry_run = widgets.Button(
            description='DRY RUN',
            button_style='primary',
            layout=widgets.Layout(width='180px', margin='10px 0px'),
            disabled=True
        )
        self.btn_import = widgets.Button(
            description='IMPORT TO DHIS2',
            button_style='danger',
            layout=widgets.Layout(width='180px', margin='10px 0px'),
            disabled=True
        )
        
        # Extra Settings Widgets
        self.chk_complete = widgets.Checkbox(
            value=False,
            description='Mark Data Set as complete after successful import',
            style={'description_width': 'initial'},
            layout=widgets.Layout(margin='5px 0px')
        )
        self.chk_ignore_mappings = widgets.Checkbox(
            value=False,
            description='Ignore missing mappings (Import mapped values only)',
            style={'description_width': 'initial'},
            layout=widgets.Layout(margin='5px 0px')
        )
        self.chk_confirm = widgets.Checkbox(
            value=False,
            description='I confirm I want to run import to destination DHIS2',
            style={'description_width': 'initial'},
            layout=widgets.Layout(margin='5px 0px')
        )
        
        # Outputs
        self.out_extraction = widgets.Output()
        self.out_validation = widgets.Output()
        self.out_dry_run = widgets.Output()
        self.out_import = widgets.Output()
        
        # Bind Actions
        self.btn_extract.on_click(self.on_extract_clicked)
        self.btn_validate.on_click(self.on_validate_clicked)
        self.btn_dry_run.on_click(self.on_dry_run_clicked)
        self.btn_import.on_click(self.on_import_clicked)
        
        # Handle partner state change
        self.partner_select.observe(self.on_partner_changed, names='value')

        self.update_partner_config()

    def on_partner_changed(self, change):
        self.update_partner_config()
        self.reset_state()

    def update_partner_config(self):
        self.current_partner_id = self.partner_select.value
        if self.current_partner_id:
            self.current_partner_config = self.loader.get_partner_config(self.current_partner_id)

    def reset_state(self):
        self.raw_df = None
        self.transformed_df = None
        self.validation_report = None
        self.btn_validate.disabled = True
        self.btn_dry_run.disabled = True
        self.btn_import.disabled = True
        self.chk_confirm.value = False
        
        # Clear output cells
        with self.out_extraction:
            clear_output()
        with self.out_validation:
            clear_output()
        with self.out_dry_run:
            clear_output()
        with self.out_import:
            clear_output()

    def on_extract_clicked(self, b):
        self.reset_state()
        self.current_period_val = self.period_select.value
        
        with self.out_extraction:
            print("Starting extraction...")
            logger.info("Starting extraction for partner: %s, period: %s", self.current_partner_id, self.current_period_val)
            
            try:
                # 1. Instantiate client
                source = self.current_partner_config.get("source", {})
                client = DHIS2Client(
                    base_url=source.get("base_url"),
                    username=source.get("username"),
                    password=source.get("password"),
                    pat=source.get("pat"),
                    verify_ssl=os.getenv("VERIFY_SSL", "true").lower() in ("true", "1")
                )
                
                # 2. Extract
                url_template = source.get("analytics_url")
                self.raw_df = extract_partner_data(client, url_template, self.current_period_val)
                
                # 3. Print Summary
                unique_de = self.raw_df['data_element'].nunique() if not self.raw_df.empty else 0
                unique_ou = self.raw_df['org_unit'].nunique() if not self.raw_df.empty else 0
                
                print("\nExtraction Result:")
                print(f"  Records extracted: {len(self.raw_df)}")
                print(f"  Organisation Units: {unique_ou}")
                print(f"  Data Elements: {unique_de}")
                
                # Enable next step
                self.btn_validate.disabled = False
                
            except Exception as e:
                logger.error("Extraction failed: %s", e)
                print(f"\nExtraction failed: {e}")

    def on_validate_clicked(self, b):
        with self.out_validation:
            clear_output()
            print("Transforming and validating mappings...")
            
            try:
                # 1. Run Mappings Transformation
                self.transformed_df = transform_partner_data(self.raw_df, self.current_partner_config)
                
                # 2. Run Mappings Validation
                self.validation_report = validate_transformed_data(self.transformed_df, self.current_partner_config)
                summary = self.validation_report.summary()
                
                # Print validation checkmarks
                de_check = "✓" if summary["missing_de_count"] == 0 else "✗"
                ou_check = "✓" if summary["missing_ou_count"] == 0 else "✗"
                pe_check = "✓" if summary["invalid_periods_count"] == 0 else "✗"
                ds_check = "✓" if not any("dataset" in err.lower() for err in summary["errors"]) else "✗"
                aoc_check = "✓" if not any("attribute" in err.lower() for err in summary["errors"]) else "✗"
                
                print("\nValidation Results:")
                print(f"  {de_check} Data Elements Mappings")
                if summary["missing_de_count"] > 0:
                    print(f"     [!] Missing mapping for: {summary['missing_de_list']}")
                print(f"  {ou_check} Organisation Units Mappings")
                if summary["missing_ou_count"] > 0:
                    print(f"     [!] Missing mapping for: {summary['missing_ou_list']}")
                print(f"  {pe_check} Period Layout")
                print(f"  {ds_check} Destination DataSet configurations")
                print(f"  {aoc_check} Attribute Option Combo configuration")
                
                # Render Mapped Data Preview Table
                print(f"\nPreview of first 10 records (Total records: {len(self.transformed_df)}):")
                preview_cols = [
                    'source_data_element', 'dest_data_element',
                    'source_org_unit', 'dest_org_unit',
                    'value'
                ]
                # Re-render as a clean pandas HTML table
                display(HTML(self.transformed_df[preview_cols].head(10).to_html(index=False)))
                
                # Enable dry run and import options
                self.btn_dry_run.disabled = False
                self.btn_import.disabled = False
                
            except Exception as e:
                logger.error("Validation failed: %s", e)
                print(f"\nTransformation/Validation failed: {e}")

    def on_dry_run_clicked(self, b):
        with self.out_dry_run:
            clear_output()
            print("Simulating import (DRY RUN)...")
            
            try:
                # Retrieve target client credentials
                dest = self.loader.get_destination_config()
                dest_client = DHIS2Client(
                    base_url=dest.get("url"),
                    username=dest.get("username"),
                    password=dest.get("password"),
                    pat=dest.get("pat"),
                    verify_ssl=dest.get("verify_ssl", True)
                )
                
                # Run dry run importer
                res = import_to_dhis2(
                    dest_client=dest_client,
                    transformed_df=self.transformed_df,
                    partner_config=self.current_partner_config,
                    dry_run=True,
                    ignore_missing_mappings=self.chk_ignore_mappings.value
                )
                
                # Output Results nicely
                print(f"\nDry Run Summary:")
                print(f"  Status: {res.get('status')}")
                print(f"  Total Extracted Records: {res.get('records_extracted')}")
                print(f"  Records with valid mappings (will import): {res.get('records_transformed')}")
                print(f"  Will mark DataSet complete: {res.get('will_mark_complete')}")
                
            except Exception as e:
                logger.error("Dry run simulation failed: %s", e)
                print(f"\nDry run simulation failed: {e}")

    def on_import_clicked(self, b):
        with self.out_import:
            clear_output()
            
            if not self.chk_confirm.value:
                print("WARNING: Please click the 'I confirm I want to run import' checkbox before running the import.")
                return

            print("Starting live import to target DHIS2 server...")
            
            try:
                # Retrieve target client credentials
                dest = self.loader.get_destination_config()
                dest_client = DHIS2Client(
                    base_url=dest.get("url"),
                    username=dest.get("username"),
                    password=dest.get("password"),
                    pat=dest.get("pat"),
                    verify_ssl=dest.get("verify_ssl", True)
                )
                
                # Execute live import
                res = import_to_dhis2(
                    dest_client=dest_client,
                    transformed_df=self.transformed_df,
                    partner_config=self.current_partner_config,
                    dry_run=False,
                    ignore_missing_mappings=self.chk_ignore_mappings.value,
                    mark_as_complete=self.chk_complete.value
                )
                
                # Render import result structure
                print(f"\nImport Outcome:")
                print(f"  Status: {res.get('status')}")
                print(f"  Message: {res.get('message')}")
                
                if "import_count" in res:
                    cnt = res["import_count"]
                    print(f"  Imported: {cnt.get('imported', 0)}")
                    print(f"  Updated: {cnt.get('updated', 0)}")
                    print(f"  Ignored: {cnt.get('ignored', 0)}")
                    print(f"  Deleted: {cnt.get('deleted', 0)}")
                    
                if "completion_report" in res:
                    c_rep = res["completion_report"]
                    print(f"  DataSet Completion Status: {c_rep.get('status')}")
                    
                if res.get("conflicts"):
                    print(f"\nConflicts found: {res.get('conflicts')}")
                    
            except Exception as e:
                logger.error("Import failed: %s", e)
                print(f"\nImport failed: {e}")

    def display(self):
        """Renders the dashboard UI box structure."""
        divider1 = widgets.HTML(value="<hr style='border-top:1px solid #ccc;'/>")
        divider2 = widgets.HTML(value="<hr style='border-top:1px solid #ccc;'/>")
        divider3 = widgets.HTML(value="<hr style='border-top:1px solid #ccc;'/>")
        divider4 = widgets.HTML(value="<hr style='border-top:1px solid #ccc;'/>")
        
        main_layout = widgets.VBox([
            self.title_label,
            self.partner_select,
            self.period_select,
            self.btn_extract,
            self.out_extraction,
            divider1,
            self.btn_validate,
            self.out_validation,
            divider2,
            self.chk_ignore_mappings,
            self.btn_dry_run,
            self.out_dry_run,
            divider3,
            self.chk_complete,
            self.chk_confirm,
            self.btn_import,
            self.out_import,
            divider4
        ], layout=widgets.Layout(padding='20px', border='1px solid #ddd', width='750px', background_color='#fafafa'))
        
        display(main_layout)

def render_dashboard():
    dashboard = ImporterDashboard()
    dashboard.display()
