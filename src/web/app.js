/**
 * DHIS2 Partner Importer - Frontend App Logic
 * Integrates with FastAPI REST endpoints, handles state management,
 * UI Tab switching, workflow wizard, file upload, and dynamic settings.
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- STATE MANAGEMENT ---
    let loadedPartners = {};
    let loadedReports = {};
    let activePartnerId = "";
    let activeReportId = "";
    let selectedYear = "2026";
    let selectedMonth = "06";
    let systemLogs = [];

    // --- DOM ELEMENT REFERENCES ---
    const tabButtons = document.querySelectorAll('.nav-tab');
    const tabPanels = document.querySelectorAll('.tab-panel');

    // Importer Tab Controls
    const selectPartner = document.getElementById('select-partner');
    const selectReport = document.getElementById('select-report');
    const selectYear = document.getElementById('select-year');
    const selectMonth = document.getElementById('select-month');
    const lblPartnerAoc = document.getElementById('lbl-partner-aoc');
    const btnExtract = document.getElementById('btn-extract');
    const btnValidate = document.getElementById('btn-validate');
    const btnDryRun = document.getElementById('btn-dryrun');
    const btnImport = document.getElementById('btn-import');
    const validationAlertBox = document.getElementById('validation-alert-box');
    const pipelineStatusText = document.getElementById('pipeline-status-text');
    const previewCard = document.getElementById('preview-card');
    const tablePreviewBody = document.getElementById('table-preview').querySelector('tbody');
    const consoleLogs = document.getElementById('console-logs');
    const btnClearLogs = document.getElementById('btn-clear-logs');

    // Mappings Tab Controls
    const btnDownloadMapping = document.getElementById('btn-download-mapping');
    const mappingDragArea = document.getElementById('mapping-drag-area');
    const fileMappingUpload = document.getElementById('file-mapping-upload');
    const uploadFileInfo = document.getElementById('upload-file-info');

    // Settings Tab Controls
    const formSettings = document.getElementById('form-settings');
    const btnResetSettings = document.getElementById('btn-reset-settings');
    const txtDestUrl = document.getElementById('txt-dest-url');
    const txtDestUsername = document.getElementById('txt-dest-username');
    const txtDestPassword = document.getElementById('txt-dest-password');
    const txtDestPat = document.getElementById('txt-dest-pat');
    const chkVerifySsl = document.getElementById('chk-verify-ssl');
    const btnAddPartnerRow = document.getElementById('btn-add-partner-row');
    const btnAddReportRow = document.getElementById('btn-add-report-row');
    const tablePartnersBody = document.querySelector('#table-settings-partners tbody');
    const tableReportsBody = document.querySelector('#table-settings-reports tbody');

    // Modal Confirmation Controls
    const modalConfirmImport = document.getElementById('modal-confirm-import');
    const btnModalCancel = document.getElementById('btn-modal-cancel');
    const btnModalConfirm = document.getElementById('btn-modal-confirm');
    const chkModalComplete = document.getElementById('chk-modal-complete');
    const chkModalIgnore = document.getElementById('chk-modal-ignore');

    // --- TAB NAVIGATION SWITCHING ---
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            
            // Switch navigation tab active class
            tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Switch visible panel
            tabPanels.forEach(panel => {
                if (panel.id === targetTab) {
                    panel.classList.add('active');
                } else {
                    panel.classList.remove('active');
                }
            });

            // Trigger refreshes depending on the tab opened
            if (targetTab === 'dashboard-tab') {
                runConnectionHealthChecks();
            } else if (targetTab === 'settings-tab') {
                fetchSettings();
            }
        });
    });

    // --- UTILITY: LOGGING SYSTEM ---
    function logToConsole(message, type = 'info') {
        const timestamp = new Date().toLocaleTimeString();
        let formattedMsg = `[${timestamp}] [${type.toUpperCase()}] ${message}\n`;
        
        systemLogs.push(formattedMsg);
        consoleLogs.textContent = systemLogs.join('');
        // Scroll console box to bottom
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    btnClearLogs.addEventListener('click', () => {
        systemLogs = [];
        consoleLogs.textContent = '';
    });

    // --- INITIALIZATION ---
    async function initApp() {
        logToConsole("Initializing DHIS2 Data Importer application...", "info");
        await fetchPartnersAndReports();
        await runConnectionHealthChecks();
    }

    // --- API: HEALTH CHECK STATUSES ---
    async function runConnectionHealthChecks() {
        logToConsole("Running connection health checks...", "info");
        
        // Show loading status for destination
        updateHealthCard('health-dest-card', 'Checking...', 'yellow');

        // Dynamically build/render cards for all configured reports first
        const grid = document.getElementById('dashboard-health-grid');
        const destCard = document.getElementById('health-dest-card');
        grid.innerHTML = '';
        grid.appendChild(destCard);

        Object.keys(loadedReports).forEach(reportId => {
            const report = loadedReports[reportId];
            const card = document.createElement('div');
            card.className = 'card status-card';
            card.id = `health-report-${reportId}`;
            card.innerHTML = `
                <div class="status-indicator yellow"></div>
                <div class="card-body">
                    <h3>Report: ${report.name}</h3>
                    <p class="server-url" style="word-break: break-all;">${report.pivot_table_url || 'No URL'}</p>
                    <span class="badge badge-warning">Checking...</span>
                </div>
            `;
            grid.appendChild(card);
        });

        try {
            const res = await fetch('/api/health');
            const data = await res.json();

            if (data.status === 'success') {
                // Update Destination status
                const dest = data.destination;
                if (dest.status === 'Connected') {
                    updateHealthCard('health-dest-card', `Online (v${dest.version})`, 'green', dest.error);
                } else {
                    updateHealthCard('health-dest-card', 'Offline', 'red', dest.error);
                }

                // Update Reports status dynamically
                const reports = data.reports;
                Object.keys(reports).forEach(reportId => {
                    const r_status = reports[reportId];
                    const cardId = `health-report-${reportId}`;
                    if (r_status.status === 'Connected') {
                        updateHealthCard(cardId, `Online (v${r_status.version})`, 'green', r_status.error);
                    } else {
                        updateHealthCard(cardId, 'Offline', 'red', r_status.error);
                    }
                });
                
                logToConsole("Health checks completed.", "info");
            }
        } catch (error) {
            logToConsole(`Failed to retrieve health status: ${error}`, "error");
            updateHealthCard('health-dest-card', 'Error', 'red', error.message);
            Object.keys(loadedReports).forEach(reportId => {
                updateHealthCard(`health-report-${reportId}`, 'Error', 'red', error.message);
            });
        }
    }

    function updateHealthCard(cardId, statusText, color, errorMsg = null) {
        const card = document.getElementById(cardId);
        if (!card) return;

        const indicator = card.querySelector('.status-indicator');
        const badge = card.querySelector('.badge');

        indicator.className = 'status-indicator ' + color;
        badge.textContent = statusText;
        badge.className = 'badge';
        if (color === 'green') badge.classList.add('badge-success');
        else if (color === 'red') badge.classList.add('badge-danger');
        else badge.classList.add('badge-warning');

        if (errorMsg) {
            card.title = `Error Details: ${errorMsg}`;
        } else {
            card.title = '';
        }
    }

    // --- API: PARTNER & REPORT DROPDOWNS ---
    async function fetchPartnersAndReports() {
        try {
            const res = await fetch('/api/partners');
            const data = await res.json();

            if (data.status === 'success') {
                loadedPartners = data.partners || {};
                loadedReports = data.reports || {};

                // 1. Populate Partners dropdown
                selectPartner.innerHTML = '<option value="">Select a partner...</option>';
                Object.keys(loadedPartners).forEach(key => {
                    const opt = document.createElement('option');
                    opt.value = key;
                    opt.textContent = loadedPartners[key].name;
                    selectPartner.appendChild(opt);
                });

                // 2. Populate Reports dropdown
                selectReport.innerHTML = '<option value="">Select a report...</option>';
                Object.keys(loadedReports).forEach(key => {
                    const opt = document.createElement('option');
                    opt.value = key;
                    opt.textContent = loadedReports[key].name;
                    selectReport.appendChild(opt);
                });

                // Set Destination label
                document.getElementById('lbl-dest-url').textContent = "Target Central Instance";
            }
        } catch (error) {
            logToConsole(`Failed loading partners and reports list: ${error}`, "error");
        }
    }

    // Handle dropdown parameter changes
    selectPartner.addEventListener('change', () => {
        activePartnerId = selectPartner.value;
        resetPipelineWizard();
        
        if (activePartnerId) {
            const partnerObj = loadedPartners[activePartnerId];
            lblPartnerAoc.textContent = partnerObj.attribute_option_combo || 'None';
            logToConsole(`Active partner switched to: ${activePartnerId}`, "info");
            btnDownloadMapping.removeAttribute('disabled');
        } else {
            lblPartnerAoc.textContent = 'None';
            btnDownloadMapping.setAttribute('disabled', 'true');
        }
    });

    selectReport.addEventListener('change', () => {
        activeReportId = selectReport.value;
        resetPipelineWizard();
    });

    selectYear.addEventListener('change', () => {
        selectedYear = selectYear.value;
        resetPipelineWizard();
    });

    selectMonth.addEventListener('change', () => {
        selectedMonth = selectMonth.value;
        resetPipelineWizard();
    });

    // --- PIPELINE RUN WORKFLOWS ---

    function resetPipelineWizard() {
        btnValidate.setAttribute('disabled', 'true');
        btnDryRun.setAttribute('disabled', 'true');
        btnImport.setAttribute('disabled', 'true');
        
        // Clear active wizard states
        document.querySelectorAll('.wizard-step').forEach(step => {
            step.className = 'wizard-step';
            if (step.id === 'step-extract') step.classList.add('active');
        });

        previewCard.classList.add('hide');
        validationAlertBox.classList.add('hide');
        pipelineStatusText.textContent = "Parameters changed. Ready to extract data.";
    }

    // 1. EXTRACTION STEP
    btnExtract.addEventListener('click', async () => {
        if (!activePartnerId || !activeReportId || !selectedYear || !selectedMonth) {
            alert("Please select a partner, a report, and a valid period (Year and Month).");
            return;
        }

        const periodVal = `${selectedYear}${selectedMonth}`;
        logToConsole(`Starting extraction for partner ${activePartnerId} using report ${activeReportId} for period ${periodVal}...`, "info");
        pipelineStatusText.textContent = "Extracting records from source pivot table...";
        
        btnExtract.setAttribute('disabled', 'true');
        
        try {
            const res = await fetch('/api/extract', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    partner_id: activePartnerId,
                    report_id: activeReportId,
                    year: selectedYear,
                    month: selectedMonth
                })
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole(`Extraction completed. Raw records found: ${data.records_extracted}`, "success");
                pipelineStatusText.textContent = `Records extracted: ${data.records_extracted}. Ready for validation.`;
                
                document.getElementById('step-extract').className = 'wizard-step completed';
                document.getElementById('step-validate').className = 'wizard-step active';
                
                btnValidate.removeAttribute('disabled');
            } else {
                throw new Error(data.detail || "Server extraction failed.");
            }
        } catch (error) {
            logToConsole(error.message, "error");
            pipelineStatusText.textContent = `Extraction failed: ${error.message}`;
        } finally {
            btnExtract.removeAttribute('disabled');
        }
    });

    // 2. VALIDATION STEP
    btnValidate.addEventListener('click', async () => {
        logToConsole("Running UID mappings translation and validation rules...", "info");
        pipelineStatusText.textContent = "Translating codes and validating mappings...";
        
        btnValidate.setAttribute('disabled', 'true');
        validationAlertBox.classList.add('hide');
        
        try {
            const res = await fetch('/api/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ partner_id: activePartnerId })
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole("Validation step completed.", "info");
                
                renderPreviewTable(data.preview);
                previewCard.classList.remove('hide');
                
                if (data.is_valid) {
                    logToConsole("All records successfully mapped and checked. Ready for Import/Simulation.", "success");
                    pipelineStatusText.textContent = "Mappings validated successfully! Ready for Dry Run or Import.";
                    
                    document.getElementById('step-validate').className = 'wizard-step completed';
                    document.getElementById('step-dryrun').className = 'wizard-step active';
                    
                    btnDryRun.removeAttribute('disabled');
                    btnImport.removeAttribute('disabled');
                } else {
                    logToConsole(`Validation failed. Missing mappings found: DEs=${data.missing_de_count}, OUs=${data.missing_ou_count}`, "warning");
                    pipelineStatusText.textContent = "Error in mapping validation. New unmapped UIDs were found.";
                    
                    document.getElementById('step-validate').className = 'wizard-step active';
                    showValidationAlert(data);
                }
            } else {
                throw new Error(data.detail || "Server validation failed.");
            }
        } catch (error) {
            logToConsole(error.message, "error");
            pipelineStatusText.textContent = `Validation failed: ${error.message}`;
        } finally {
            btnValidate.removeAttribute('disabled');
        }
    });

    function renderPreviewTable(records) {
        tablePreviewBody.innerHTML = '';
        if (!records || records.length === 0) {
            tablePreviewBody.innerHTML = '<tr><td colspan="5" class="text-center">No transformed data available.</td></tr>';
            return;
        }

        records.forEach(row => {
            const tr = document.createElement('tr');
            const deClass = row.dest_data_element ? '' : 'text-danger font-bold';
            const ouClass = row.dest_org_unit ? '' : 'text-danger font-bold';

            tr.innerHTML = `
                <td>${row.source_data_element || '-'}</td>
                <td class="${deClass}">${row.dest_data_element || 'Unmapped'}</td>
                <td>${row.source_org_unit || '-'}</td>
                <td class="${ouClass}">${row.dest_org_unit || 'Unmapped'}</td>
                <td>${row.value || '0'}</td>
            `;
            tablePreviewBody.appendChild(tr);
        });
    }

    function showValidationAlert(data) {
        validationAlertBox.innerHTML = '';
        
        let deListHtml = data.missing_de_list.length > 0 ? `<li><strong>Data Elements:</strong> <code>${data.missing_de_list.join(', ')}</code></li>` : '';
        let ouListHtml = data.missing_ou_list.length > 0 ? `<li><strong>Organisation Units:</strong> <code>${data.missing_ou_list.join(', ')}</code></li>` : '';
        
        validationAlertBox.innerHTML = `
            <div style="background-color: #ffeef0; border-left: 5px solid #d83b01; padding: 15px; border-radius: 4px; font-family: sans-serif;">
                <h4 style="color: #d83b01; margin-top: 0; margin-bottom: 8px;">[⚠️] Unmapped Source UIDs Detected</h4>
                <p style="margin: 0 0 10px 0; font-size: 0.9em; color: #333;">
                    New source codes were found that do not have a translation corresponding to the destination:
                </p>
                <ul style="margin: 0 0 15px 20px; font-size: 0.9em; color: #444; line-height: 1.4;">
                    ${deListHtml}
                    ${ouListHtml}
                </ul>
                <a href="/api/mapping/download/${activePartnerId}?t=${Date.now()}" download style="background-color: #d83b01; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block; font-size: 0.9em; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    📥 Download Updated Mapping Sheet
                </a>
                <p style="margin: 10px 0 0 0; font-size: 0.8em; color: #555;">
                    Open the file in Excel, fill in the blanks in the <strong>Destination UID</strong>, <strong>Name</strong>, <strong>District</strong>, and <strong>County</strong> columns, save it, and upload it using the mappings manager.
                </p>
            </div>
        `;
        validationAlertBox.classList.remove('hide');
    }

    // 3. DRY RUN (SIMULATION)
    btnDryRun.addEventListener('click', async () => {
        logToConsole("Starting Dry Run import simulation to target server...", "info");
        pipelineStatusText.textContent = "Simulating data write on DHIS2...";
        
        btnDryRun.setAttribute('disabled', 'true');
        const ignoreMissing = chkModalIgnore.checked;
        
        try {
            const res = await fetch('/api/dry-run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ partner_id: activePartnerId, ignore_missing_mappings: ignoreMissing })
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole(`Dry Run finished. Server status: ${data.import_status}`, "success");
                logToConsole(`Summary: Extracted=${data.records_extracted}, Mapped=${data.records_transformed}, MarkComplete=${data.will_mark_complete}`, "info");
                
                pipelineStatusText.textContent = `Simulation completed! Status: ${data.import_status}. Ready for definitive Import.`;
                
                document.getElementById('step-dryrun').className = 'wizard-step completed';
                document.getElementById('step-import').className = 'wizard-step active';
            } else {
                throw new Error(data.detail || "Server Dry Run failed.");
            }
        } catch (error) {
            logToConsole(error.message, "error");
            pipelineStatusText.textContent = `Simulation failed: ${error.message}`;
        } finally {
            btnDryRun.removeAttribute('disabled');
        }
    });

    // 4. IMPORT STEP
    btnImport.addEventListener('click', () => {
        chkModalComplete.checked = false;
        const isValidationOk = document.getElementById('step-validate').classList.contains('completed');
        chkModalIgnore.checked = !isValidationOk;
        modalConfirmImport.classList.remove('hide');
    });

    btnModalCancel.addEventListener('click', () => {
        modalConfirmImport.classList.add('hide');
    });

    btnModalConfirm.addEventListener('click', async () => {
        modalConfirmImport.classList.add('hide');
        const complete = chkModalComplete.checked;
        const ignoreMissing = chkModalIgnore.checked;
        
        logToConsole("Executing LIVE import to target DHIS2 server...", "warning");
        pipelineStatusText.textContent = "Executing final data import...";
        
        btnImport.setAttribute('disabled', 'true');
        btnDryRun.setAttribute('disabled', 'true');
        
        try {
            const res = await fetch('/api/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    partner_id: activePartnerId,
                    ignore_missing_mappings: ignoreMissing,
                    mark_as_complete: complete
                })
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole("LIVE IMPORT COMPLETED SUCCESSFULLY!", "success");
                logToConsole(`Outcome Status: ${data.import_status}`, "success");
                logToConsole(`Message: ${data.message}`, "info");
                
                if (data.import_count) {
                    const c = data.import_count;
                    logToConsole(`Records written: Imported=${c.imported || 0}, Updated=${c.updated || 0}, Ignored=${c.ignored || 0}, Deleted=${c.deleted || 0}`, "info");
                }
                
                if (data.completion_report) {
                    logToConsole(`DataSet Completion Status: ${data.completion_report.status || 'N/A'}`, "info");
                }

                pipelineStatusText.textContent = `Import completed! Records imported: ${data.import_count?.imported || 0}, updated: ${data.import_count?.updated || 0}.`;
                document.getElementById('step-import').className = 'wizard-step completed';
            } else {
                throw new Error(data.detail || "Server Live Import failed.");
            }
        } catch (error) {
            logToConsole(error.message, "error");
            pipelineStatusText.textContent = `Import failed: ${error.message}`;
        } finally {
            btnImport.removeAttribute('disabled');
            btnDryRun.removeAttribute('disabled');
        }
    });

    // --- MAPPINGS MANAGEMENT ---

    btnDownloadMapping.addEventListener('click', () => {
        if (!activePartnerId) return;
        logToConsole(`Downloading current mapping file for ${activePartnerId}...`, "info");
        window.location.href = `/api/mapping/download/${activePartnerId}`;
    });

    mappingDragArea.addEventListener('click', () => {
        if (!activePartnerId) {
            alert("Please select a partner before uploading a mapping file.");
            return;
        }
        fileMappingUpload.click();
    });

    mappingDragArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        mappingDragArea.classList.add('drag-over');
    });

    mappingDragArea.addEventListener('dragleave', () => {
        mappingDragArea.classList.remove('drag-over');
    });

    mappingDragArea.addEventListener('drop', (e) => {
        e.preventDefault();
        mappingDragArea.classList.remove('drag-over');
        if (!activePartnerId) {
            alert("Please select a partner before uploading a mapping file.");
            return;
        }
        if (e.dataTransfer.files.length > 0) {
            handleMappingFileSelect(e.dataTransfer.files[0]);
        }
    });

    fileMappingUpload.addEventListener('change', () => {
        if (fileMappingUpload.files.length > 0) {
            handleMappingFileSelect(fileMappingUpload.files[0]);
        }
    });

    async function handleMappingFileSelect(file) {
        uploadFileInfo.textContent = `Uploading ${file.name}...`;
        logToConsole(`Uploading mapping file: ${file.name} for partner ${activePartnerId}...`, "info");

        const formData = new FormData();
        formData.append('partner_id', activePartnerId);
        formData.append('file', file);

        try {
            const res = await fetch('/api/mapping/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                uploadFileInfo.textContent = `✓ Mapping '${file.name}' uploaded successfully!`;
                uploadFileInfo.className = "margin-top-10 text-center font-bold text-success";
                logToConsole(`Mapping uploaded and applied successfully: ${file.name}`, "success");
                fileMappingUpload.value = "";
                
                const isExtractDone = document.getElementById('step-extract').classList.contains('completed');
                if (isExtractDone) {
                    btnValidate.click();
                }
            } else {
                throw new Error(data.detail || "Upload failed on server.");
            }
        } catch (error) {
            uploadFileInfo.textContent = `Upload error: ${error.message}`;
            uploadFileInfo.className = "margin-top-10 text-center font-bold text-danger";
            logToConsole(`Upload failed: ${error.message}`, "error");
        }
    }

    // --- CONFIGURATIONS AND SETTINGS ---

    async function fetchSettings() {
        logToConsole("Loading connection configurations...", "info");
        try {
            const res = await fetch('/api/settings');
            const data = await res.json();

            if (data.status === 'success') {
                const settings = data.settings;
                
                // Populate Destination details
                txtDestUrl.value = settings.destination_url;
                txtDestUsername.value = settings.destination_username;
                txtDestPassword.value = settings.destination_password;
                txtDestPat.value = settings.destination_pat || "";
                chkVerifySsl.checked = settings.verify_ssl;

                // Populate Partners CRUD table
                renderPartnersTable(settings.partners || {});

                // Populate Reports CRUD table
                renderReportsTable(settings.reports || {});
                
                logToConsole("Configurations loaded successfully.", "info");
            }
        } catch (error) {
            logToConsole(`Failed loading settings: ${error}`, "error");
        }
    }

    function renderPartnersTable(partners) {
        tablePartnersBody.innerHTML = '';
        Object.keys(partners).forEach(pId => {
            const partner = partners[pId];
            appendPartnerRow(pId, partner.name || "", partner.attribute_option_combo || "", partner.data_set || "", partner.mapping_file || "");
        });
    }

    function appendPartnerRow(id = "", name = "", aoc = "", dataSet = "", mapping = "") {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="text" class="form-control val-partner-id" value="${id}" placeholder="e.g. MZ-PSI" style="font-family: monospace;" required></td>
            <td><input type="text" class="form-control val-partner-name" value="${name}" placeholder="e.g. MZ-PSI" required></td>
            <td><input type="text" class="form-control val-partner-aoc" value="${aoc}" placeholder="e.g. PSI_AOC_UID" style="font-family: monospace;" required></td>
            <td><input type="text" class="form-control val-partner-dataset" value="${dataSet}" placeholder="e.g. DataSet UID" style="font-family: monospace;" required></td>
            <td><input type="text" class="form-control val-partner-mapping" value="${mapping}" placeholder="e.g. psi.xlsx" style="font-family: monospace;" required></td>
            <td><button type="button" class="btn btn-danger btn-sm btn-delete-row">Delete</button></td>
        `;
        tablePartnersBody.appendChild(tr);
    }

    function renderReportsTable(reports) {
        tableReportsBody.innerHTML = '';
        Object.keys(reports).forEach(rId => {
            const r = reports[rId];
            appendReportRow(rId, r.name || "", r.pivot_table_url || "", r.username || "", r.password || "");
        });
    }

    function appendReportRow(id = "", name = "", url = "", user = "", pwd = "") {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="text" class="form-control val-report-id" value="${id}" placeholder="e.g. psi_monthly" style="font-family: monospace;" required></td>
            <td><input type="text" class="form-control val-report-name" value="${name}" placeholder="e.g. PSI Monthly Report" required></td>
            <td><input type="text" class="form-control val-report-url" value="${url}" placeholder="e.g. https://...pe={period}..." required></td>
            <td><input type="text" class="form-control val-report-username" value="${user}" placeholder="Source Username"></td>
            <td><input type="password" class="form-control val-report-password" value="${pwd}" placeholder="Source Password"></td>
            <td><button type="button" class="btn btn-danger btn-sm btn-delete-row">Delete</button></td>
        `;
        tableReportsBody.appendChild(tr);
    }

    // Dynamic row addition triggers
    btnAddPartnerRow.addEventListener('click', () => appendPartnerRow());
    btnAddReportRow.addEventListener('click', () => appendReportRow());

    // Row deletion triggers (event delegation)
    tablePartnersBody.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-delete-row')) {
            e.target.closest('tr').remove();
        }
    });

    tableReportsBody.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-delete-row')) {
            e.target.closest('tr').remove();
        }
    });

    btnResetSettings.addEventListener('click', () => {
        fetchSettings();
    });

    // Form submit settings
    formSettings.addEventListener('submit', async (e) => {
        e.preventDefault();
        logToConsole("Saving connection settings...", "info");

        // 1. Gather Partners map from DOM table rows
        const partnersMap = {};
        const pRows = tablePartnersBody.querySelectorAll('tr');
        let hasPartnerErrors = false;
        
        pRows.forEach(row => {
            const pId = row.querySelector('.val-partner-id').value.trim();
            const pName = row.querySelector('.val-partner-name').value.trim();
            const pAoc = row.querySelector('.val-partner-aoc').value.trim();
            const pDataSet = row.querySelector('.val-partner-dataset').value.trim();
            const pMapping = row.querySelector('.val-partner-mapping').value.trim();

            if (pId) {
                partnersMap[pId] = {
                    name: pName,
                    attribute_option_combo: pAoc,
                    data_set: pDataSet,
                    mapping_file: pMapping
                };
            } else {
                hasPartnerErrors = true;
            }
        });

        // 2. Gather Reports map from DOM table rows
        const reportsMap = {};
        const rRows = tableReportsBody.querySelectorAll('tr');
        let hasReportErrors = false;

        rRows.forEach(row => {
            const rId = row.querySelector('.val-report-id').value.trim();
            const rName = row.querySelector('.val-report-name').value.trim();
            const rUrl = row.querySelector('.val-report-url').value.trim();
            const rUser = row.querySelector('.val-report-username').value.trim();
            const rPwd = row.querySelector('.val-report-password').value.trim();

            if (rId) {
                reportsMap[rId] = {
                    name: rName,
                    pivot_table_url: rUrl,
                    username: rUser,
                    password: rPwd
                };
            } else {
                hasReportErrors = true;
            }
        });

        if (hasPartnerErrors || hasReportErrors) {
            alert("Please make sure all ID values are filled out correctly.");
            return;
        }

        const payload = {
            destination_url: txtDestUrl.value.trim(),
            destination_username: txtDestUsername.value.trim(),
            destination_password: txtDestPassword.value.trim(),
            destination_pat: txtDestPat.value.trim(),
            verify_ssl: chkVerifySsl.checked,
            partners: partnersMap,
            reports: reportsMap
        };

        try {
            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole("Settings updated successfully.", "success");
                alert("Settings saved successfully!");
                await fetchPartnersAndReports(); // Refresh local list state
                await runConnectionHealthChecks(); // Refresh health cards on dashboard
            } else {
                throw new Error(data.detail || "Failed to update settings.");
            }
        } catch (error) {
            logToConsole(error.message, "error");
            alert(`Failed to save settings: ${error.message}`);
        }
    });

    // Start App
    initApp();
});
