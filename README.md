# DHIS2 Partner Data Importer

A robust, enterprise-grade data migration middleware designed to extract data records from multiple source DHIS2 instances (using Pivot Table Analytics CSV exports), dynamically validate and translate UIDs based on Excel mappings, and upload the transformed datasets directly into a target central DHIS2 instance.

---

## Key Features

- **Dynamic Pivot Table Extraction:** Supports absolute, fully configured DHIS2 Analytics CSV URLs.
- **Host-Domain Decoupling Credentials:** Decouples reports from credentials. The system automatically parses the base domain from the report's Pivot Table URL and looks up the configured username/password credentials.
- **Split-UID Partition Mapping:** Handles category option combos dynamically (e.g., partitioning `mhE3DzNMOmw.nQiuxrt5KHG` into element and category combos). If no combo is defined in the destination, it defaults to the DHIS2 central server default.
- **Detailed Validation Reports:** Reports missing mappings (Data Elements or Organisation Units) in separate scrollable code boxes. Synonyms like `Province` (instead of `District`) are supported in mapping templates.
- **Excel Upload Mappings Manager:** Allows downloading the template containing missing source UIDs, completing translations in Excel, and uploading it back to the platform.
- **Built-in Cache Cleaner:** Features a native Cache Cleaner button that purges LocalStorage, SessionStorage, Cache API, and forces a hard reload with cache-busting tokens.
- **Robust Health Checks:** Displays real-time connectivity status (Online/Offline) for the target central server and configured source domains.
- **Persistence Configurations:** Saves changes made on the UI settings tab to local YAML configurations, bypassing Git to prevent losing configurations when updates are fetched.

---

## Project Structure

```text
dhis2_partner_importer/
├── config/                     # Shared configurations
│   ├── mappings/               # Directory containing mappings.xlsx
│   └── partners.yaml           # Default template configurations (fallback)
├── src/                        # Python Application Source Code
│   ├── app.py                  # Main FastAPI REST endpoints controller
│   ├── config/                 # Dynamic local configuration loader
│   ├── dhis2/                  # DHIS2 API client and importer tasks
│   ├── transformation/         # Split translation engine (dot-syntax partitioning)
│   ├── validation/             # Validation logic report compiling
│   └── web/                    # Static frontend (HTML/CSS/JS with Outfit style)
├── tests/                      # Pipeline and transformation unit tests
├── Dockerfile                  # Application Docker recipe
└── docker-compose.yml          # Container configuration with Traefik integration
```

---

## Local Development Installation

### Prerequisites
- Python 3.10 or higher
- Git

### Steps
1. **Clone the Repository:**
   ```bash
   git clone https://github.com/echivambo/dhis2_partner_importer.git
   cd dhis2_partner_importer
   ```

2. **Create a Virtual Environment:**
   - **On Windows:**
     ```bash
     python -m venv venv
     venv\Scripts\activate
     ```
   - **On Linux/macOS:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables Config:**
   Create a `.env` file in the project root:
   ```env
   DESTINATION_DHIS2_URL=https://play.dhis2.org/2.40.0
   DESTINATION_DHIS2_USERNAME=admin
   DESTINATION_DHIS2_PASSWORD=district
   DESTINATION_DHIS2_PAT=
   VERIFY_SSL=true
   ```

5. **Run Unit Tests (Validation check):**
   ```bash
   python -m unittest tests/test_pipeline.py
   ```

6. **Start the FastAPI Server:**
   ```bash
   python -m uvicorn src.app:app --port 8005 --host 127.0.0.1 --reload
   ```
   Open `http://127.0.0.1:8005` in your browser.

---

## Production / Server Installation using Docker

To run the application in a production environment or a Linux server, Docker is the recommended method.

### Prerequisites
- Docker Engine
- Docker Compose

### Steps
1. **Prepare Environment Settings:**
   Ensure `.env` file is present in the workspace root with correct production central DHIS2 destination credentials.

2. **Spin Up Containers:**
   Launch the system in background mode:
   ```bash
   docker compose up -d --build
   ```

   This builds the FastAPI image, starts the container, mounts the `./config` volume for persistence, and links it with Traefik for reverse-proxy routing.

3. **Verify running containers:**
   ```bash
   docker compose ps
   ```

4. **Access the App:**
   Open the port `8005` on your host machine: `http://localhost:8005`.

5. **Stop Services:**
   To stop the running application:
   ```bash
   docker compose down
   ```

---

## Configurations Guide

### 1. Excel Mapping File
The Excel sheet `config/mappings/mappings.xlsx` has two sheets:
- `data_elements`: Maps `Source UID` -> `Destination UID` and `Name`.
- `organisation_units`: Maps `Source UID` -> `Destination UID`, `Name`, `Province`, and `Country`.

If new unmapped source UIDs are found during the validation step, a template will be generated. Download it, fill in the translations, and upload it back.

### 2. Settings tab
Configure multiple partners and report Pivot Table URLs from the **Settings** tab. The system parses domain origins dynamically (e.g. `https://data.psi-mis.org`) and matches credentials saved under **Manage Source Servers** to perform seamless background authentication during extraction steps.
