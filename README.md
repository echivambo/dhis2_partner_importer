# DHIS2 Partner Importer

A robust, python-based ETL (Extract-Transform-Load) utility to synchronize monthly Facility reports across different DHIS2 partner instances.

This application connects to partner DHIS2 source APIs, extracts raw data element CSV responses from Analytics API endpoints, applies customizable translations for both Data Element and Organisation Unit UIDs on a per-partner basis, validates data consistency, simulates the import status (Dry Run), and imports data valuesets safely into a target DHIS2 server.

## Features

- **Isolated Partner Configurations**: Add, modify, or remove partner details and mapping rules in structured YAML files without touching the core codebase.
- **Dynamic Periods**: Friendly month selectors mapping automatically to DHIS2 `YYYYMM` formats.
- **Strict Data Validation**: Prevents importing if data contains unmapped Data Elements, unmapped Organisation Units, or invalid periods.
- **Dry Run Mode**: Simulates the import and details what records are valid and what conflicts would occur.
- **Secure Credentials**: Never exposes credentials, Authorization headers, or tokens in configurations or log outputs.
- **Dockerized Jupyter Interface**: Runs easily inside Docker with Traefik reverse-proxy routing to `http://dhis2-importer.localhost`.

---

## Folder Structure

```
dhis2_partner_importer/
│
├── .env                  # Configuration credentials (gitignored)
├── .env.example          # Sample environment variables template
├── .gitignore            # Git exclusion definitions
├── Dockerfile            # Docker instructions
├── docker-compose.yml    # App + Traefik containers orchestration
├── requirements.txt      # Python dependencies
├── README.md             # Setup and running instructions
│
├── config/
│   ├── partners.yaml     # Global partner endpoints & credential references
│   └── mappings/         # Mappings per partner
│       ├── pathfinder.yaml
│       └── psi.yaml
│
├── notebooks/
│   └── dhis2_importer.ipynb # Launcher notebook for the ipywidgets Dashboard
│
└── src/
    ├── config/           # Configuration loader
    ├── dhis2/            # DHIS2 Auth Client, Analytics, and Target Importers
    ├── transformation/   # Mapping translation logic
    ├── validation/       # Data Element, OU, and Period validations
    ├── utils/            # Logging and Period utilities
    └── ui/               # Widget dashboard rendering
```

---

## Getting Started

### 1. Setup Environment Credentials
Copy `.env.example` into a new `.env` file at the project root:
```bash
cp .env.example .env
```
Fill in the destination DHIS2 server URL, credentials (either `USERNAME` + `PASSWORD` or `PAT` token), and custom partner credentials:
```ini
VERIFY_SSL=true

# Destination Target Server
DESTINATION_DHIS2_URL=https://play.dhis2.org/2.40.0
DESTINATION_DHIS2_USERNAME=admin
DESTINATION_DHIS2_PASSWORD=district

# Source Partner (MZ-PATHFINDER)
PATHFINDER_DHIS2_USERNAME=pathfinder_user
PATHFINDER_DHIS2_PASSWORD=pathfinder_password
```

### 2. Run Locally (Python Virtual Environment)
1. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch Jupyter Lab:
   ```bash
   jupyter lab
   ```
4. Navigate to `notebooks/dhis2_importer.ipynb` and run the cell to display the dashboard.

### 3. Run with Docker & Traefik
1. Start the Docker containers:
   ```bash
   docker compose up -d --build
   ```
2. The Traefik reverse proxy will automatically capture the port bindings.
3. Open your browser and go to:
   [http://dhis2-importer.localhost](http://dhis2-importer.localhost)
   *(Note: Jupyter Lab token is disabled by default in Docker for local ease of use).*

---

## Configuring Partners & Mappings

### Adding a New Partner
1. Open `config/partners.yaml` and add a new partner record:
   ```yaml
   partners:
     NEW-PARTNER:
       name: "New Partner Name"
       source:
         base_url: "https://source-instance.org"
         analytics_url: "https://source-instance.org/api/analytics.csv?dimension=dx:xA01Im2qXJ2&dimension=ou:x1WEJQu4rJp&dimension=pe:{period}"
         username_env: "NEW_PARTNER_USER"
         password_env: "NEW_PARTNER_PWD"
       destination:
         data_set: "TARGET_DATASET_UID"
         attribute_option_combo: "TARGET_AOC_UID"
         mapping_file: "new_partner.yaml"
   ```
2. Create `config/mappings/new_partner.yaml` to specify translation mappings:
   ```yaml
   data_elements:
     xA01Im2qXJ2: "DEST_DE_xA01"
     
   organisation_units:
     x1WEJQu4rJp: "DEST_OU_x1WE"
     
   category_option_combos:
     default: "DEFAULT_COC_UID"
   ```
3. Define the credentials (`NEW_PARTNER_USER` and `NEW_PARTNER_PWD`) in your `.env` file.

---

## Running Tests

To run the unit test suite covering pipeline components:
```bash
python -m unittest tests/test_pipeline.py
```
