import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import requests

from src.utils.periods import to_dhis2_period, to_human_period
from src.dhis2.analytics import normalize_columns, extract_partner_data
from src.transformation.transformer import transform_partner_data
from src.validation.validator import validate_transformed_data
from src.dhis2.importer import create_data_value_set_payload, import_to_dhis2
from src.dhis2.client import DHIS2Client, DHIS2AuthError, DHIS2HTTPError, DHIS2ConnectionError

class TestDHIS2Pipeline(unittest.TestCase):

    def setUp(self):
        # Configure a standard partner configuration dictionary for testing
        self.partner_config = {
            "name": "TEST-PARTNER",
            "source": {
                "base_url": "https://source.dhis2.org",
                "analytics_url": "https://source.dhis2.org/api/analytics.csv?pe={period}&dx=DE_SRC_1"
            },
            "destination": {
                "data_set": "DS_DEST_123",
                "attribute_option_combo": "AOC_DEST_456"
            },
            "mappings": {
                "data_elements": {
                    "DE_SRC_1": "DE_DST_1",
                    "DE_SRC_2": "DE_DST_2"
                },
                "organisation_units": {
                    "OU_SRC_1": "OU_DST_1"
                },
                "category_option_combos": {
                    "default": "DEFAULT_COC"
                }
            }
        }

    # 1. Period Conversion & Invalid Periods
    def test_period_conversion(self):
        self.assertEqual(to_dhis2_period("January 2026"), "202601")
        self.assertEqual(to_dhis2_period("Janeiro 2026"), "202601")
        self.assertEqual(to_dhis2_period("2026-02"), "202602")
        self.assertEqual(to_dhis2_period("202603"), "202603")
        
        # Test human format extraction
        self.assertEqual(to_human_period("202601", "en"), "January 2026")
        self.assertEqual(to_human_period("202601", "pt"), "Janeiro 2026")
        
        # Invalid period formats
        with self.assertRaises(ValueError):
            to_dhis2_period("2026-13")
        with self.assertRaises(ValueError):
            to_dhis2_period("NotMonth 2026")
        with self.assertRaises(ValueError):
            to_dhis2_period("")

    # 2. URL Generation
    def test_url_generation(self):
        url_template = self.partner_config["source"]["analytics_url"]
        period = "202601"
        compiled = url_template.replace("{period}", period)
        self.assertIn("pe=202601", compiled)
        self.assertNotIn("{period}", compiled)

    # 3. Data Element & Org Unit Mappings (Transformer)
    def test_mappings(self):
        raw_data = pd.DataFrame({
            "data_element": ["DE_SRC_1", "DE_SRC_2"],
            "org_unit": ["OU_SRC_1", "OU_SRC_1"],
            "period": ["202601", "202601"],
            "value": [10, 20]
        })
        transformed = transform_partner_data(raw_data, self.partner_config)
        
        self.assertEqual(transformed.loc[0, "dest_data_element"], "DE_DST_1")
        self.assertEqual(transformed.loc[1, "dest_data_element"], "DE_DST_2")
        self.assertEqual(transformed.loc[0, "dest_org_unit"], "OU_DST_1")
        self.assertEqual(transformed.loc[0, "dest_attribute_option_combo"], "AOC_DEST_456")

    # 4. Missing Mapping Detection (Validator)
    def test_missing_mapping_detection(self):
        raw_data = pd.DataFrame({
            "data_element": ["DE_SRC_1", "DE_SRC_UNMAPPED"],
            "org_unit": ["OU_SRC_UNMAPPED", "OU_SRC_1"],
            "period": ["202601", "202601"],
            "value": [10, 20]
        })
        transformed = transform_partner_data(raw_data, self.partner_config)
        report = validate_transformed_data(transformed, self.partner_config)
        
        self.assertFalse(report.is_valid)
        self.assertIn("DE_SRC_UNMAPPED", report.missing_data_elements)
        self.assertIn("OU_SRC_UNMAPPED", report.missing_organisation_units)

    # 5. Data Value Set Generation (Payload)
    def test_data_value_set_payload(self):
        transformed = pd.DataFrame({
            "dest_data_element": ["DE_DST_1"],
            "dest_org_unit": ["OU_DST_1"],
            "period": ["202601"],
            "dest_category_option_combo": ["DEFAULT_COC"],
            "dest_attribute_option_combo": ["AOC_DEST_456"],
            "value": ["10"]
        })
        payload = create_data_value_set_payload(transformed, "DS_DEST_123", "AOC_DEST_456")
        
        self.assertEqual(payload["dataSet"], "DS_DEST_123")
        self.assertEqual(len(payload["dataValues"]), 1)
        self.assertEqual(payload["dataValues"][0]["dataElement"], "DE_DST_1")
        self.assertEqual(payload["dataValues"][0]["orgUnit"], "OU_DST_1")
        self.assertEqual(payload["dataValues"][0]["value"], "10")

    # 6. HTTP and Auth Client Errors (Mocked calls)
    @patch('requests.Session.request')
    def test_client_auth_failure(self, mock_request):
        # Mock 401 Unauthorized
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response
        
        client = DHIS2Client(base_url="https://play.dhis2.org/2.40.0", username="admin", password="wrongpassword")
        with self.assertRaises(DHIS2AuthError):
            client.get("api/me")

    @patch('requests.Session.request')
    def test_client_http_error(self, mock_request):
        # Mock 500 Internal Server Error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        # Simulate raise_for_status raising HTTPError
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Error")
        mock_request.return_value = mock_response
        
        client = DHIS2Client(base_url="https://play.dhis2.org/2.40.0", username="admin", password="district")
        with self.assertRaises(DHIS2HTTPError):
            client.get("api/dataValueSets")

    @patch('requests.Session.request')
    def test_client_empty_response(self, mock_request):
        # Mock successful request but returning empty body
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_request.return_value = mock_response
        
        client = DHIS2Client(base_url="https://play.dhis2.org/2.40.0")
        df = extract_partner_data(client, "https://play.dhis2.org/api/analytics.csv", "202601")
        self.assertTrue(df.empty)

    def test_config_loader_excel_csv(self):
        import tempfile
        import os
        from src.config.config_loader import ConfigLoader

        # Create a temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Test Excel Mapping Loader
            excel_path = os.path.join(tmpdir, "test_mapping.xlsx")
            
            de_df = pd.DataFrame([{"Source": "src_de_1", "Dest": "dst_de_1"}])
            ou_df = pd.DataFrame([{"Source": "src_ou_1", "Dest": "dst_ou_1"}])
            
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                de_df.to_excel(writer, sheet_name="data_elements", index=False)
                ou_df.to_excel(writer, sheet_name="organisation_units", index=False)
                
            loader = ConfigLoader()
            excel_mappings = loader._load_excel_mappings(excel_path)
            
            self.assertIn("src_de_1", excel_mappings["data_elements"])
            self.assertEqual(excel_mappings["data_elements"]["src_de_1"], "dst_de_1")
            self.assertIn("src_ou_1", excel_mappings["organisation_units"])
            self.assertEqual(excel_mappings["organisation_units"]["src_ou_1"], "dst_ou_1")
            
            # 2. Test CSV Mapping Loader (with type column)
            csv_path = os.path.join(tmpdir, "test_mapping.csv")
            csv_df = pd.DataFrame([
                {"type": "data_element", "source": "src_de_csv", "destination": "dst_de_csv"},
                {"type": "organisation_unit", "source": "src_ou_csv", "destination": "dst_ou_csv"}
            ])
            csv_df.to_csv(csv_path, index=False)
            
            csv_mappings = loader._load_csv_mappings(csv_path)
            
            self.assertIn("src_de_csv", csv_mappings["data_elements"])
            self.assertEqual(csv_mappings["data_elements"]["src_de_csv"], "dst_de_csv")
            self.assertIn("src_ou_csv", csv_mappings["organisation_units"])
            self.assertEqual(csv_mappings["organisation_units"]["src_ou_csv"], "dst_ou_csv")

if __name__ == '__main__':
    unittest.main()
