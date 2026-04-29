document.addEventListener("DOMContentLoaded", () => {
    // Character count
    const textarea = document.getElementById("script_text");
    const charCount = document.getElementById("char-count");
    if (textarea && charCount) {
        textarea.addEventListener("input", () => {
            charCount.textContent = textarea.value.length;
            charCount.style.color = textarea.value.length > 30000 ? "var(--error)" : "";
        });
    }

    // File upload UI
    const fileInput = document.getElementById("script_file");
    const fileUpload = document.getElementById("file-upload");
    const fileName = document.getElementById("file-name");
    if (fileInput && fileUpload && fileName) {
        fileInput.addEventListener("change", () => {
            if (fileInput.files.length > 0) {
                fileName.textContent = "已选择: " + fileInput.files[0].name;
            } else {
                fileName.textContent = "";
            }
        });

        fileUpload.addEventListener("dragover", (e) => {
            e.preventDefault();
            fileUpload.classList.add("dragover");
        });

        fileUpload.addEventListener("dragleave", () => {
            fileUpload.classList.remove("dragover");
        });

        fileUpload.addEventListener("drop", (e) => {
            e.preventDefault();
            fileUpload.classList.remove("dragover");
            fileInput.files = e.dataTransfer.files;
            if (fileInput.files.length > 0) {
                fileName.textContent = "已选择: " + fileInput.files[0].name;
            }
        });
    }

    // Submit button loading state
    const form = document.getElementById("analyze-form");
    const submitBtn = document.getElementById("submit-btn");
    if (form && submitBtn) {
        form.addEventListener("submit", () => {
            const btnText = submitBtn.querySelector(".btn-text");
            const btnLoader = submitBtn.querySelector(".btn-loader");
            if (btnText && btnLoader) {
                btnText.style.display = "none";
                btnLoader.style.display = "inline";
                submitBtn.disabled = true;
            }
        });
    }

    // Tabs on result page
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabPanels = document.querySelectorAll(".tab-panel");
    tabBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.tab;
            tabBtns.forEach((b) => b.classList.remove("active"));
            tabPanels.forEach((p) => p.classList.remove("active"));
            btn.classList.add("active");
            const panel = document.getElementById("tab-" + target);
            if (panel) panel.classList.add("active");
        });
    });
});
