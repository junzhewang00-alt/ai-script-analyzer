#!/bin/bash
# v2.2 deploy — paste this entire block into server terminal
cd /home/ai-script-analyzer || exit 1
python3 << 'PYEOF'
import re, os

BASE = "/home/ai-script-analyzer"

# ====== models.py ======
with open(f"{BASE}/models.py", "r") as f: c = f.read()
c = c.replace("REGISTER_BONUS = 30", "REGISTER_BONUS = 200")
with open(f"{BASE}/models.py", "w") as f: f.write(c)
print("[OK] models.py")

# ====== pay_bp.py ======
with open(f"{BASE}/pay_bp.py", "r") as f: c = f.read()
c = c.replace('result.get("return_code") == 0', 'result.get("return_code") != 1')
with open(f"{BASE}/pay_bp.py", "w") as f: f.write(c)
print("[OK] pay_bp.py")

# ====== app.py ======
with open(f"{BASE}/app.py", "r") as f: c = f.read()

# 1) @login_required on /prompts
c = c.replace(
    '@app.route("/prompts")\ndef prompts_studio():',
    '@app.route("/prompts")\n@login_required\ndef prompts_studio():'
)
# 2) @login_required on /api/config GET
c = c.replace(
    '@app.route("/api/config", methods=["GET"])\ndef api_config_get():',
    '@app.route("/api/config", methods=["GET"])\n@login_required\ndef api_config_get():'
)
# 3) @login_required on /api/config POST
c = c.replace(
    '@app.route("/api/config", methods=["POST"])\ndef api_config_save():',
    '@app.route("/api/config", methods=["POST"])\n@login_required\ndef api_config_save():'
)
# 4) Remove upfront credit deduction (the block between "script_text)" and "sid = _get_sid()")
c = re.sub(
    r'(\n\s*# 积分检查\n\s*cost = get_analysis_cost\(len\(script_text\)\)\n\s*if current_user\.credits < cost:\n\s*return render_template\(\s*"index\.html",\s*error=f"积分不足！本次分析需要 \{cost\} 积分，当前余额 \{current_user\.credits\} 积分。"\s*f\'.*?\)\s*\n\s*)_deduct_credits\(cost, f"剧本分析 \(\{[^}]+\}字\)"\)\s*\n\s*',
    '\n    ',
    c,
    flags=re.DOTALL
)
# If regex didn't match, try simpler approach
if '_deduct_credits(cost, f"剧本分析' in c:
    # Remove lines containing the old credit logic
    lines = c.split('\n')
    new_lines = []
    skip = False
    for line in lines:
        if '# 积分检查' in line and 'cost = get_analysis_cost' in lines[lines.index(line)+1] if lines.index(line)+1 < len(lines) else False:
            # skip next ~7 lines
            skip = 7
            continue
        if skip > 0:
            skip -= 1
            continue
        new_lines.append(line)
    c = '\n'.join(new_lines)

with open(f"{BASE}/app.py", "w") as f: f.write(c)
print("[OK] app.py")

# ====== templates/base.html ======
with open(f"{BASE}/templates/base.html", "r") as f: c = f.read()
old = '<p>基于大语言模型的短剧多维度分析工具</p>'
new = '<p>基于大语言模型的短剧多维度分析工具 &nbsp;<span style="opacity:0.5;font-size:0.78rem;">v2.2</span></p>'
if old in c:
    c = c.replace(old, new)
with open(f"{BASE}/templates/base.html", "w") as f: f.write(c)
print("[OK] base.html")

# ====== .env.example ======
with open(f"{BASE}/.env.example", "r") as f: c = f.read()
if "PAYJS_MCHID" not in c:
    c += """
# PayJS 支付配置（微信扫码支付）
PAYJS_MCHID=your-payjs-mchid
PAYJS_SECRET=your-payjs-secret-key
PAYJS_NOTIFY_URL=https://your-domain.com/pay/notify
"""
with open(f"{BASE}/.env.example", "w") as f: f.write(c)
print("[OK] .env.example")

# ====== templates/manual.html ======
with open(f"{BASE}/templates/manual.html", "r") as f: c = f.read()

# Add overview export button
c = c.replace(
    '<span class="dim-status idle" id="overview-status">待生成</span>\n        </div>',
    '<span class="dim-status idle" id="overview-status">待生成</span>\n            <button class="btn btn-sm btn-outline dim-export-btn" id="export-overview-btn" style="display:none" onclick="exportOverview(event)" title="导出概览">📋</button>\n        </div>'
)
# Add dimension export button
c = c.replace(
    '<span class="dim-status idle" id="status-{{ loop.index0 }}">待分析</span>\n        </div>',
    '<span class="dim-status idle" id="status-{{ loop.index0 }}">待分析</span>\n            <button class="btn btn-sm btn-outline dim-export-btn" id="export-dim-btn-{{ loop.index0 }}" style="display:none" onclick="exportDimension(event, {{ loop.index0 }})" title="导出此维度">📋</button>\n        </div>'
)
# Replace old action button with dropdown
old_action = '<button class="btn btn-outline" id="export-btn" style="display:none" onclick="exportResults()">\n        📋 导出结果\n    </button>'
new_action = '''<div class="export-dropdown" id="export-group" style="display:none">
        <button class="btn btn-outline" id="export-btn" onclick="toggleExportMenu(event)">
            📋 导出结果 ▾
        </button>
        <div class="export-menu" id="export-menu" style="display:none">
            <button class="export-menu-item" onclick="exportResults('md'); toggleExportMenu()">📋 Markdown (.md)</button>
            <button class="export-menu-item" onclick="exportResults('txt'); toggleExportMenu()">📄 纯文本 (.txt)</button>
            <button class="export-menu-item" onclick="exportResults('pdf'); toggleExportMenu()">🖨️ PDF (.pdf)</button>
        </div>
    </div>'''
if old_action in c:
    c = c.replace(old_action, new_action)
    print("[OK] manual.html action bar")
else:
    print("[WARN] manual.html action bar pattern not found")

# Replace old export JS block
old_showExport = 'function showExportBtn() {\n    var doneCount = document.querySelectorAll(".dim-status.done").length;\n    var exportBtn = document.getElementById("export-btn");\n    if (exportBtn && doneCount >= 1) {\n        exportBtn.style.display = "inline-flex";\n    }\n}'
new_showExport = 'function showExportBtn() {\n    var doneCount = document.querySelectorAll(".dim-status.done").length;\n    var exportGroup = document.getElementById("export-group");\n    if (exportGroup && doneCount >= 1) {\n        exportGroup.style.display = "";\n    }\n}'
if old_showExport in c:
    c = c.replace(old_showExport, new_showExport)

# Replace exportResults + downloadExport with new multi-format versions
old_exportResults = '''function exportResults() {
    var parts = [];
    parts.push("# AI 短剧剧本分析报告\\n");
    parts.push("\\n---\\n\\n");'''
if old_exportResults in c:
    # Find the end of exportResults and downloadExport, replace everything up to the next </script>
    idx = c.find(old_exportResults)
    # Find the closing script tag after this point
    end_idx = c.find('</script>', idx)
    # Find start of next script block
    next_script = c.find('<script>\n// Auto-poll', idx)

    new_js_block = '''function showExportBtn() {
    var doneCount = document.querySelectorAll(".dim-status.done").length;
    var exportGroup = document.getElementById("export-group");
    if (exportGroup && doneCount >= 1) {
        exportGroup.style.display = "";
    }
}

function toggleExportMenu(e) {
    if (e) e.stopPropagation();
    var menu = document.getElementById("export-menu");
    var fmtPicker = document.getElementById("fmt-picker");
    if (fmtPicker) fmtPicker.style.display = "none";
    menu.style.display = menu.style.display === "none" ? "" : "none";
}

// Close dropdown on outside click
document.addEventListener("click", function(e) {
    var menu = document.getElementById("export-menu");
    var fmtPicker = document.getElementById("fmt-picker");
    var target = e.target;
    var isExportBtn = target.closest(".dim-export-btn") || target.closest("#export-btn");
    var isInMenu = target.closest(".export-menu-item");
    var isInPicker = target.closest(".fmt-picker-btns");
    if (menu && !isInMenu) menu.style.display = "none";
    if (fmtPicker && !isExportBtn && !isInPicker) fmtPicker.style.display = "none";
});

// ---- Single-dimension export ----

function exportDimension(ev, index) {
    var card = document.getElementById("dim-" + index);
    if (!card) return;
    var label = card.querySelector(".dim-label");
    var body = card.querySelector(".dim-body");
    if (!label || !body) return;
    var labelText = label.textContent.trim();
    var content = body.textContent.trim();
    if (!content) return;
    showFormatPicker(ev, function(fmt) {
        var text = "# " + labelText + "\\n\\n" + content + "\\n";
        outputExport(text, labelText, fmt);
    });
}

function exportOverview(ev) {
    var body = document.getElementById("overview-body");
    if (!body) return;
    var content = body.textContent.trim();
    if (!content) return;
    showFormatPicker(ev, function(fmt) {
        var text = "# 分析概览\\n\\n" + content + "\\n";
        outputExport(text, "分析概览", fmt);
    });
}

function showFormatPicker(ev, callback) {
    var picker = document.getElementById("fmt-picker");
    if (!picker) {
        picker = document.createElement("div");
        picker.id = "fmt-picker";
        picker.className = "fmt-picker";
        picker.innerHTML = '<div class="fmt-picker-btns">' +
            '<button data-fmt="md">📋 MD</button>' +
            '<button data-fmt="txt">📄 TXT</button>' +
            '<button data-fmt="pdf">🖨️ PDF</button>' +
            '</div>';
        document.body.appendChild(picker);
        picker.addEventListener("click", function(e) {
            var btn = e.target.closest("button");
            if (btn && btn.dataset.fmt) {
                picker.style.display = "none";
                callback(btn.dataset.fmt);
            }
            e.stopPropagation();
        });
    }
    picker.style.display = "";
    if (ev) {
        picker.style.left = (ev.clientX + 10) + "px";
        picker.style.top = (ev.clientY - 10) + "px";
    }
}

// ---- Full export ----

function exportResults(fmt) {
    var parts = ["# AI 短剧剧本分析报告\\n\\n---\\n\\n"];

    document.querySelectorAll(".dim-card").forEach(function(card) {
        var label = card.querySelector(".dim-label");
        var body = card.querySelector(".dim-body");
        if (label && body) {
            var labelText = label.textContent.trim();
            var content = body.textContent.trim();
            if (content && content !== "点击下方按钮开始分析") {
                parts.push("## " + labelText + "\\n\\n" + content + "\\n\\n---\\n");
            }
        }
    });

    var overviewBody = document.getElementById("overview-body");
    if (overviewBody) {
        var ovContent = overviewBody.textContent.trim();
        if (ovContent && ovContent.indexOf("所有维度完成后") === -1) {
            parts.push("\\n## 分析概览\\n\\n" + ovContent + "\\n");
        }
    }

    outputExport(parts.join("\\n"), "剧本分析报告", fmt);
}

// ---- Output: dispatch by format ----

function outputExport(text, label, fmt) {
    if (fmt === "txt") {
        var plain = text
            .replace(/^#{1,6}\\s+/gm, "")
            .replace(/\\*\\*(.+?)\\*\\*/g, "$1")
            .replace(/\\*(.+?)\\*/g, "$1")
            .replace(/`{1,3}[^`]*`{1,3}/g, "")
            .replace(/^---\\s*$/gm, "──────────────────")
            .replace(/\\[([^\\]]+)\\]\\([^)]+\\)/g, "$1");
        downloadAsFile(plain, label, "txt", "text/plain;charset=utf-8");
        flashExportBtn();
    } else if (fmt === "pdf") {
        var mdHtml = text
            .replace(/^### (.+)$/gm, '<h3>$1</h3>')
            .replace(/^## (.+)$/gm, '<h2>$1</h2>')
            .replace(/^# (.+)$/gm, '<h1>$1</h1>')
            .replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>')
            .replace(/^---\\s*$/gm, '<hr>')
            .replace(/\\n\\n/g, '</p><p>')
            .replace(/\\n/g, '<br>');
        mdHtml = '<p>' + mdHtml + '</p>';
        var w = window.open("", "_blank", "width=800,height=600");
        w.document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + label + '</title>' +
            '<style>body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;max-width:720px;margin:40px auto;padding:20px;line-height:1.9;color:#2c2c2c;}' +
            'h1{font-size:1.6em;border-bottom:2px solid #c8a34e;padding-bottom:8px;}h2{font-size:1.25em;color:#c8a34e;margin-top:28px;}h3{font-size:1.05em;}' +
            'hr{border:0;border-top:1px solid #ddd;margin:24px 0;}@media print{body{margin:0;padding:0;}}</style></head><body>' + mdHtml + '</body></html>');
        w.document.close();
        w.focus();
        setTimeout(function() { w.print(); }, 500);
        flashExportBtn();
    } else {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function() {
                flashExportBtn();
            }).catch(function() {
                downloadAsFile(text, label, "md", "text/markdown;charset=utf-8");
                flashExportBtn();
            });
        } else {
            downloadAsFile(text, label, "md", "text/markdown;charset=utf-8");
            flashExportBtn();
        }
    }
}

function downloadAsFile(text, label, ext, mime) {
    var blob = new Blob([text], {type: mime});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = label + "_" + jobId + "." + ext;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function flashExportBtn() {
    var btn = document.getElementById("export-btn");
    if (!btn) return;
    var origHTML = btn.innerHTML;
    btn.innerHTML = "✓ 已导出";
    btn.style.borderColor = "#4a8";
    btn.style.color = "#4a8";
    setTimeout(function() {
        btn.innerHTML = origHTML;
        btn.style.borderColor = "";
        btn.style.color = "";
    }, 2000);
}'''

    if next_script > idx:
        # Replace from exportResults to the auto-poll script
        old_block_start = c.rfind('function showExportBtn', 0, next_script)
        if old_block_start > 0:
            c = c[:old_block_start] + new_js_block + '\n' + c[next_script:]
            print("[OK] manual.html JS block replaced")
    else:
        print("[WARN] Could not find replacement boundaries in manual.html")

# Add export button show logic in updateDimStatus
c = c.replace(
    '        runningCount--;\n        if (status === "error") {',
    '        runningCount--;\n        if (status === "done") {\n            var exportDimBtn = document.getElementById("export-dim-btn-" + index);\n            if (exportDimBtn) exportDimBtn.style.display = "";\n        }\n        if (status === "error") {'
)

# Add overview export button show logic in pollOverview done handler
c = c.replace(
    '                document.getElementById("overview-card").classList.add("done");\n                showExportBtn();',
    '                document.getElementById("overview-card").classList.add("done");\n                showExportBtn();\n                var ovExportBtn = document.getElementById("export-overview-btn");\n                if (ovExportBtn) ovExportBtn.style.display = "";'
)

# Add overview export button show in pollResults overview section
c = c.replace(
    '                    document.getElementById("overview-card").classList.add("done");\n                } else if (ov.status === "error")',
    '                    document.getElementById("overview-card").classList.add("done");\n                    var ovExportBtn2 = document.getElementById("export-overview-btn");\n                    if (ovExportBtn2) ovExportBtn2.style.display = "";\n                } else if (ov.status === "error")'
)

with open(f"{BASE}/templates/manual.html", "w") as f: f.write(c)
print("[OK] manual.html")

# ====== static/style.css ======
with open(f"{BASE}/static/style.css", "r") as f: c = f.read()

new_css = '''
.dim-export-btn {
    margin-left: auto;
    padding: 2px 8px;
    font-size: 0.75rem;
    line-height: 1.4;
    border-color: transparent;
    opacity: 0.6;
    transition: all 0.2s;
}
.dim-export-btn:hover {
    opacity: 1;
    border-color: var(--gold-dark);
    background: rgba(200,163,78,0.08);
}

/* ---- Export Dropdown ---- */
.export-dropdown {
    position: relative;
    display: inline-flex;
}
.export-menu {
    position: absolute;
    bottom: 100%;
    left: 0;
    margin-bottom: 6px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    z-index: 100;
    min-width: 190px;
    overflow: hidden;
}
.export-menu-item {
    display: block;
    width: 100%;
    padding: 10px 16px;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: 0.85rem;
    text-align: left;
    cursor: pointer;
    transition: all 0.15s;
}
.export-menu-item:hover {
    background: rgba(200,163,78,0.08);
    color: var(--gold-light);
}

/* ---- Format Picker (floating) ---- */
.fmt-picker {
    position: fixed;
    z-index: 200;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    overflow: hidden;
}
.fmt-picker-btns {
    display: flex;
}
.fmt-picker-btns button {
    padding: 8px 14px;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
}
.fmt-picker-btns button:hover {
    background: rgba(200,163,78,0.1);
    color: var(--gold-light);
}
.fmt-picker-btns button + button {
    border-left: 1px solid var(--border);
}
'''

# Insert after .dim-btn-cancel:hover block
anchor = '.dim-btn-cancel:hover {\n    background: rgba(200, 57, 43, 0.08);\n    border-color: rgba(200, 57, 43, 0.3);\n}'
if anchor in c:
    c = c.replace(anchor, anchor + new_css)
    print("[OK] style.css")
else:
    # Try alternate anchor
    alt_anchor = '/* ---- Overview Card ---- */'
    if alt_anchor in c:
        c = c.replace(alt_anchor, new_css + '\n' + alt_anchor)
        print("[OK] style.css (alt anchor)")
    else:
        print("[WARN] style.css anchor not found")

with open(f"{BASE}/static/style.css", "w") as f: f.write(c)

print("\n=== All files updated ===")
print("Restarting server...")
import subprocess
subprocess.run(["systemctl", "restart", "ai-script-analyzer"])
print("Done! Server restarted.")
PYEOF
