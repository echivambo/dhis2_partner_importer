/**
 * DHIS2 Partner Importer - Frontend App Logic
 * Integrates with FastAPI REST endpoints, handles state management,
 * UI Tab switching, workflow wizard, file upload, and credential configuration.
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- STATE MANAGEMENT ---
    let appSettings = {};
    let activePartnerId = "";
    let selectedPeriod = "";
    let systemLogs = [];

    // --- DOM ELEMENT REFERENCES ---
    const tabButtons = document.querySelectorAll('.nav-tab');
    const tabPanels = document.querySelectorAll('.tab-panel');

    // Importer Tab Controls
    const selectPartner = document.getElementById('select-partner');
    const selectPeriod = document.getElementById('select-period');
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

    // Pathfinder inputs
    const txtPathfinderUsername = document.getElementById('txt-pathfinder-username');
    const txtPathfinderPassword = document.getElementById('txt-pathfinder-password');
    const txtPathfinderPat = document.getElementById('txt-pathfinder-pat');

    // PSI inputs
    const txtPsiUsername = document.getElementById('txt-psi-username');
    const txtPsiPassword = document.getElementById('txt-psi-password');
    const txtPsiPat = document.getElementById('txt-psi-pat');

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
        // Scroll console box to the bottom
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    btnClearLogs.addEventListener('click', () => {
        systemLogs = [];
        consoleLogs.textContent = '';
    });

    // --- INITIALIZATION ---
    async function initApp() {
        logToConsole("Initializing DHIS2 Data Importer application...", "info");
        await fetchPartners();
        populatePeriodDropdown();
        await runConnectionHealthChecks();
    }

    // --- API: HEALTH CHECK STATUSES ---
    async function runConnectionHealthChecks() {
        logToConsole("Running connection health checks...", "info");
        
        // Show loading statuses
        updateHealthCard('health-dest-card', 'Checking...', 'yellow');
        updateHealthCard('health-pathfinder-card', 'Checking...', 'yellow');
        updateHealthCard('health-psi-card', 'Checking...', 'yellow');

        try {
            const res = await fetch('/api/health');
            const data = await res.json();

            if (data.status === 'success') {
                // Update Destination Instance status
                const dest = data.destination;
                if (dest.status === 'Connected') {
                    updateHealthCard('health-dest-card', `Online (v${dest.version})`, 'green', dest.error);
                } else {
                    updateHealthCard('health-dest-card', 'Offline', 'red', dest.error);
                }

                // Update Partners status
                const partners = data.partners;
                
                const pf = partners['MZ-PATHFINDER'];
                if (pf && pf.status === 'Connected') {
                    updateHealthCard('health-pathfinder-card', `Online (v${pf.version})`, 'green', pf.error);
                } else {
                    updateHealthCard('health-pathfinder-card', 'Offline', 'red', pf ? pf.error : 'No configuration found');
                }

                const psi = partners['MZ-PSI'];
                if (psi && psi.status === 'Connected') {
                    updateHealthCard('health-psi-card', `Online (v${psi.version})`, 'green', psi.error);
                } else {
                    updateHealthCard('health-psi-card', 'Offline', 'red', psi ? psi.error : 'No configuration found');
                }
                
                logToConsole("Health checks completed.", "info");
            }
        } catch (error) {
            logToConsole(`Failed to retrieve health status: ${error}`, "error");
            updateHealthCard('health-dest-card', 'Error', 'red', error.message);
            updateHealthCard('health-pathfinder-card', 'Error', 'red', error.message);
            updateHealthCard('health-psi-card', 'Error', 'red', error.message);
        }
    }

    function updateHealthCard(cardId, statusText, color, errorMsg = null) {
        const card = document.getElementById(cardId);
        if (!card) return;

        const indicator = card.querySelector('.status-indicator');
        const badge = card.querySelector('.badge');

        // Update indicator color bar
        indicator.className = 'status-indicator ' + color;

        // Update badge text and colors
        badge.textContent = statusText;
        badge.className = 'badge';
        if (color === 'green') badge.classList.add('badge-success');
        else if (color === 'red') badge.classList.add('badge-danger');
        else badge.classList.add('badge-warning');

        // Setup hover tooltip if error exists
        if (errorMsg) {
            card.title = `Error Details: ${errorMsg}`;
        } else {
            card.title = '';
        }
    }

    // --- API: PARTNER DROPDOWNS ---
    async function fetchPartners() {
        try {
            const res = await fetch('/api/partners');
            const data = await res.json();

            if (data.status === 'success') {
                selectPartner.innerHTML = '<option value="">Select a partner...</option>';
                Object.keys(data.partners).forEach(key => {
                    const opt = document.createElement('option');
                    opt.value = key;
                    opt.textContent = data.partners[key].name;
                    selectPartner.appendChild(opt);
                });
                
                // Read global urls for labels on the dashboard
                document.getElementById('lbl-dest-url').textContent = "Target Central Instance";
                document.getElementById('lbl-pathfinder-url').textContent = data.partners['MZ-PATHFINDER']?.source?.base_url || "https://data.psi-mis.org";
                document.getElementById('lbl-psi-url').textContent = data.partners['MZ-PSI']?.source?.base_url || "https://another-dhis2.org";
            }
        } catch (error) {
            logToConsole(`Failed loading partners list: ${error}`, "error");
        }
    }

    function populatePeriodDropdown() {
        selectPeriod.innerHTML = '<option value="">Select a period...</option>';
        
        // Generate list of past 24 months mapping to friendly text and YYYYMM format
        const monthsEn = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
        const today = new Date();
        
        for (let i = 0; i < 24; i++) {
            const date = new Date(today.getFullYear(), today.getMonth() - i, 1);
            const year = date.getFullYear();
            const monthVal = String(date.getMonth() + 1).padStart(2, '0');
            
            const value = `${year}${monthVal}`;
            const text = `${monthsEn[date.getMonth()]} ${year}`;
            
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = text;
            selectPeriod.appendChild(opt);
        }
    }

    // Handle partner dropdown change
    selectPartner.addEventListener('change', () => {
        activePartnerId = selectPartner.value;
        resetPipelineWizard();
        
        if (activePartnerId) {
            logToConsole(`Active partner switched to: ${activePartnerId}`, "info");
            btnDownloadMapping.removeAttribute('disabled');
        } else {
            btnDownloadMapping.setAttribute('disabled', 'true');
        }
    });

    selectPeriod.addEventListener('change', () => {
        selectedPeriod = selectPeriod.value;
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
        if (!activePartnerId || !selectedPeriod) {
            alert("Please select a partner and a valid period.");
            return;
        }

        logToConsole(`Starting extraction for ${activePartnerId} in period ${selectedPeriod}...`, "info");
        pipelineStatusText.textContent = "Extracting records from source server...";
        
        btnExtract.setAttribute('disabled', 'true');
        
        try {
            const res = await fetch('/api/extract', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ partner_id: activePartnerId, period: selectedPeriod })
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole(`Extraction completed. Raw records found: ${data.records_extracted}`, "success");
                pipelineStatusText.textContent = `Records extracted: ${data.records_extracted}. Ready for validation.`;
                
                // Advance step tracker
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
                
                // Show mapping preview table
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
                    
                    // Show custom beautiful HTML alert box with download updated template button
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
                    Open the file in Excel, fill in the blanks in the <strong>Destination UID</strong> column, save it, and upload it using the mappings manager.
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

    // 4. IMPORT STEP (TRIGGER CONFIRM DIALOG)
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
                
                if (data.conflicts && data.conflicts.length > 0) {
                    logToConsole(`Conflicts reported: ${JSON.stringify(data.conflicts)}`, "warning");
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

    // Download active mapping sheet
    btnDownloadMapping.addEventListener('click', () => {
        if (!activePartnerId) return;
        logToConsole(`Downloading current mapping file for ${activePartnerId}...`, "info");
        window.location.href = `/api/mapping/download/${activePartnerId}`;
    });

    // Drag & Drop event bindings
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
                logToConsole(`Mapping uploaded and applied successfully: ${file.name}`, "success");
                
                // Clear file input value
                fileMappingUpload.value = "";
                
                // Re-run validation if raw data is already extracted
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
                appSettings = data.settings;
                
                // Populate forms
                txtDestUrl.value = appSettings.destination_url;
                txtDestUsername.value = appSettings.destination_username;
                txtDestPassword.value = appSettings.destination_password;
                txtDestPat.value = appSettings.destination_pat || "";
                chkVerifySsl.checked = appSettings.verify_ssl;

                // Pathfinder
                const pf = appSettings.partners.PATHFINDER;
                txtPathfinderUsername.value = pf.username;
                txtPathfinderPassword.value = pf.password;
                txtPathfinderPat.value = pf.pat || "";

                // PSI
                const psi = appSettings.partners.PSI;
                txtPsiUsername.value = psi.username;
                txtPsiPassword.value = psi.password;
                txtPsiPat.value = psi.pat || "";
                
                logToConsole("Configurations loaded successfully.", "info");
            }
        } catch (error) {
            logToConsole(`Failed loading settings: ${error}`, "error");
        }
    }

    // Reset settings changes
    btnResetSettings.addEventListener('click', () => {
        fetchSettings();
    });

    // Form submit settings
    formSettings.addEventListener('submit', async (e) => {
        e.preventDefault();
        logToConsole("Saving connection settings...", "info");

        const updatedSettings = {
            destination_url: txtDestUrl.value,
            destination_username: txtDestUsername.value,
            destination_password: txtDestPassword.value,
            destination_pat: txtDestPat.value,
            verify_ssl: chkVerifySsl.checked,
            partners: {
                PATHFINDER: {
                    username: txtPathfinderUsername.value,
                    password: txtPathfinderPassword.value,
                    pat: txtPathfinderPat.value
                },
                PSI: {
                    username: txtPsiUsername.value,
                    password: txtPsiPassword.value,
                    pat: txtPsiPat.value
                }
            }
        };

        try {
            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updatedSettings)
            });
            const data = await res.json();

            if (res.ok && data.status === 'success') {
                logToConsole("Settings updated successfully.", "success");
                alert("Settings saved successfully!");
                await runConnectionHealthChecks(); // Refresh statuses on dashboard
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
