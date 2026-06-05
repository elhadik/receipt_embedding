document.addEventListener("DOMContentLoaded", () => {
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const scannerOverlay = document.getElementById("scanner-overlay");
    
    const resultCard = document.getElementById("result-card");
    const detailsCard = document.getElementById("details-card");
    
    // Status Badge & Banner
    const statusBadge = document.getElementById("status-badge");
    const statusReasonBox = document.getElementById("status-reason-box");
    const statusReasonText = document.getElementById("status-reason-text");
    
    // KPI Fields
    const kpiMerchant = document.getElementById("kpi-merchant");
    const kpiDatetime = document.getElementById("kpi-datetime");
    const kpiTotal = document.getElementById("kpi-total");
    
    // Checklist Items
    const checkIsReceipt = document.getElementById("check-is-receipt");
    const checkIsReceiptDetail = document.getElementById("check-is-receipt-detail");
    const checkMath = document.getElementById("check-math");
    const checkMathDetail = document.getElementById("check-math-detail");
    const checkDuplicate = document.getElementById("check-duplicate");
    const checkDuplicateDetail = document.getElementById("check-duplicate-detail");
    
    // Tables & Details
    const lineItemsBody = document.getElementById("line-items-body");
    const finSubtotal = document.getElementById("fin-subtotal");
    const finTax = document.getElementById("fin-tax");
    const finTip = document.getElementById("fin-tip");
    const finDiscount = document.getElementById("fin-discount");
    const finFees = document.getElementById("fin-fees");
    const finTotal = document.getElementById("fin-total");
    
    // Metadata
    const metaConfidence = document.getElementById("meta-confidence");
    const metaPayment = document.getElementById("meta-payment");
    const metaNumber = document.getElementById("meta-number");
    
    // History Table
    const historyBody = document.getElementById("history-body");

    // Load initial history log
    loadHistory();

    // Setup file drag and drop
    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    ["dragleave", "dragend"].forEach(type => {
        dropZone.addEventListener(type, () => {
            dropZone.classList.remove("dragover");
        });
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    function handleFileSelect(file) {
        // Validate file size (max 5MB)
        if (file.size > 5 * 1024 * 1024) {
            alert("File size exceeds the 5MB limit.");
            return;
        }

        // Validate file type
        const allowedTypes = ["image/png", "image/jpeg", "image/jpg", "application/pdf"];
        if (!allowedTypes.includes(file.type)) {
            alert("File type not supported. Please upload a PNG, JPG, JPEG, or PDF file.");
            return;
        }

        uploadFile(file);
    }

    function uploadFile(file) {
        // Show scanning animation overlay
        scannerOverlay.classList.add("active");

        const formData = new FormData();
        formData.append("receipt", file);

        // Get CSRF Token
        const csrfTokenMeta = document.querySelector("meta[name='csrf-token']");
        const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute("content") : "";

        fetch("/upload", {
            method: "POST",
            headers: {
                "X-CSRF-Token": csrfToken
            },
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw new Error(err.error || "Upload failed"); });
            }
            return response.json();
        })
        .then(data => {
            renderResults(data);
            loadHistory();
        })
        .catch(err => {
            console.error("Error processing receipt:", err);
            alert("Error: " + err.message);
        })
        .finally(() => {
            // Hide scanning animation overlay
            scannerOverlay.classList.remove("active");
        });
    }

    function renderResults(data) {
        // Show result cards
        resultCard.classList.remove("hidden");
        
        // Handle Decision status
        const isApproved = data.status === "Approved";
        
        statusBadge.textContent = isApproved ? "APPROVED" : "REJECTED";
        statusBadge.replaceChildren(); // Safe clear
        statusBadge.appendChild(document.createTextNode(isApproved ? "APPROVED" : "REJECTED"));
        
        statusBadge.className = "badge " + (isApproved ? "approved" : "rejected");
        
        statusReasonBox.className = "status-reason-box " + (isApproved ? "approved" : "rejected");
        statusReasonText.textContent = data.reason;

        // Populate KPIs
        const parsed = data.extraction || {};
        const isReceiptBool = parsed.is_receipt || false;
        const rData = parsed.receipt_data || {};
        
        const merchant = rData.merchant || {};
        kpiMerchant.textContent = merchant.name || "-";
        
        const trans = rData.transaction || {};
        kpiDatetime.textContent = (trans.date || "") + (trans.time ? " " + trans.time : "") || "-";
        
        const financials = rData.financials || {};
        const currency = trans.currency || "$";
        const totalVal = financials.total !== null ? `${currency} ${parseFloat(financials.total).toFixed(2)}` : "-";
        kpiTotal.textContent = totalVal;

        // Populate Audit Checklists
        // 1. Is Receipt check
        updateCheckItem(
            checkIsReceipt,
            checkIsReceiptDetail,
            isReceiptBool,
            isReceiptBool ? "Document verified as a financial receipt." : parsed.validation_message || "Not a valid receipt format."
        );

        // 2. Math audit check
        const mathResult = data.math_validation || {};
        updateCheckItem(
            checkMath,
            checkMathDetail,
            mathResult.is_valid,
            mathResult.is_valid ? "Arithmetic integrity check passed." : (mathResult.errors || []).join("; ")
        );

        // 3. Duplicate check
        const dupResult = data.duplicate_check || {};
        const isUnique = !dupResult.is_duplicate;
        let dupMsg = "No duplicate submissions detected.";
        if (dupResult.is_duplicate) {
            const detail = dupResult.match_details || {};
            dupMsg = `Matches ${detail.file_name} with ${(detail.similarity * 100).toFixed(0)}% similarity.`;
        }
        updateCheckItem(
            checkDuplicate,
            checkDuplicateDetail,
            isUnique,
            dupMsg
        );

        // Populate detailed cards if it's a receipt
        if (isReceiptBool) {
            detailsCard.classList.remove("hidden");
            
            // Populate line items table (secure creation)
            lineItemsBody.replaceChildren();
            const items = rData.line_items || [];
            
            if (items.length === 0) {
                const tr = document.createElement("tr");
                const td = document.createElement("td");
                td.setAttribute("colspan", "4");
                td.textContent = "No items extracted.";
                tr.appendChild(td);
                lineItemsBody.appendChild(tr);
            } else {
                items.forEach(item => {
                    const tr = document.createElement("tr");
                    
                    const tdDesc = document.createElement("td");
                    tdDesc.textContent = item.description || "Unknown Item";
                    
                    const tdQty = document.createElement("td");
                    tdQty.className = "text-right";
                    tdQty.textContent = item.quantity !== null ? item.quantity : "-";
                    
                    const tdUnit = document.createElement("td");
                    tdUnit.className = "text-right";
                    tdUnit.textContent = item.unit_price !== null ? parseFloat(item.unit_price).toFixed(2) : "-";
                    
                    const tdTotal = document.createElement("td");
                    tdTotal.className = "text-right font-bold";
                    tdTotal.textContent = item.total_price !== null ? parseFloat(item.total_price).toFixed(2) : "-";
                    
                    tr.appendChild(tdDesc);
                    tr.appendChild(tdQty);
                    tr.appendChild(tdUnit);
                    tr.appendChild(tdTotal);
                    
                    lineItemsBody.appendChild(tr);
                });
            }

            // Populate Financial breakdowns
            finSubtotal.textContent = financials.subtotal !== null ? `${currency} ${parseFloat(financials.subtotal).toFixed(2)}` : "-";
            finTax.textContent = financials.tax_amount !== null ? `${currency} ${parseFloat(financials.tax_amount).toFixed(2)}` : "-";
            finTip.textContent = financials.tip_amount !== null ? `${currency} ${parseFloat(financials.tip_amount).toFixed(2)}` : "-";
            finDiscount.textContent = financials.discount_amount !== null ? `${currency} ${parseFloat(financials.discount_amount).toFixed(2)}` : "-";
            finFees.textContent = financials.fees_amount !== null ? `${currency} ${parseFloat(financials.fees_amount).toFixed(2)}` : "-";
            finTotal.textContent = financials.total !== null ? `${currency} ${parseFloat(financials.total).toFixed(2)}` : "-";

            // Populate Extra Metadata
            metaConfidence.textContent = parsed.confidence_score !== undefined ? (parsed.confidence_score * 100).toFixed(0) + "%" : "-";
            const method = rData.payment_method || {};
            metaPayment.textContent = method.type ? (method.type + (method.card_last_four ? ` (*${method.card_last_four})` : "")) : "-";
            metaNumber.textContent = trans.receipt_number || "-";
        } else {
            detailsCard.classList.add("hidden");
        }
    }

    function updateCheckItem(itemElement, detailElement, isPassed, detailText) {
        const icon = itemElement.querySelector(".check-icon");
        if (isPassed) {
            icon.className = "check-icon success";
            icon.setAttribute("data-lucide", "check-circle");
        } else {
            icon.className = "check-icon failed";
            icon.setAttribute("data-lucide", "alert-circle");
        }
        detailElement.textContent = detailText;
        lucide.createIcons(); // Refresh dynamic icons
    }

    function loadHistory() {
        fetch("/history")
        .then(response => response.json())
        .then(history => {
            renderHistory(history);
        })
        .catch(err => console.error("Error loading submission history:", err));
    }

    function renderHistory(history) {
        historyBody.replaceChildren(); // Safe clear
        
        if (history.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.setAttribute("colspan", "6");
            td.className = "text-center";
            td.textContent = "No submissions processed yet.";
            tr.appendChild(td);
            historyBody.appendChild(tr);
            return;
        }

        history.forEach(item => {
            const tr = document.createElement("tr");
            
            // Format ISO timestamp
            const tsDate = new Date(item.timestamp);
            const tsFormatted = tsDate.toLocaleDateString() + " " + tsDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            
            const tdTime = document.createElement("td");
            tdTime.textContent = tsFormatted;
            
            const tdFile = document.createElement("td");
            tdFile.textContent = item.file_name;
            
            const tdMerchant = document.createElement("td");
            tdMerchant.textContent = item.merchant_name || "-";
            
            const tdDate = document.createElement("td");
            tdDate.textContent = item.date || "-";
            
            const tdTotal = document.createElement("td");
            tdTotal.className = "text-right font-bold";
            tdTotal.textContent = item.total ? `$ ${parseFloat(item.total).toFixed(2)}` : "-";
            
            const tdStatus = document.createElement("td");
            // Highlight based on duplicate status or just show complete
            const spanStatus = document.createElement("span");
            spanStatus.className = "success-text";
            spanStatus.textContent = "Processed";
            tdStatus.appendChild(spanStatus);

            tr.appendChild(tdTime);
            tr.appendChild(tdFile);
            tr.appendChild(tdMerchant);
            tr.appendChild(tdDate);
            tr.appendChild(tdTotal);
            tr.appendChild(tdStatus);

            historyBody.appendChild(tr);
        });
    }

    const clearDbBtn = document.getElementById("clear-db-btn");
    if (clearDbBtn) {
        clearDbBtn.addEventListener("click", () => {
            if (confirm("Are you sure you want to clear the local submissions database and delete all uploaded files? This action cannot be undone.")) {
                const csrfTokenMeta = document.querySelector("meta[name='csrf-token']");
                const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute("content") : "";
                
                fetch("/clear_database", {
                    method: "POST",
                    headers: {
                        "X-CSRF-Token": csrfToken
                    }
                })
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(err => { throw new Error(err.error || "Failed to clear database"); });
                    }
                    return response.json();
                })
                .then(data => {
                    alert(data.message || "Database cleared successfully.");
                    resultCard.classList.add("hidden");
                    detailsCard.classList.add("hidden");
                    loadHistory();
                })
                .catch(err => {
                    console.error("Error clearing database:", err);
                    alert("Error: " + err.message);
                });
            }
        });
    }
});

