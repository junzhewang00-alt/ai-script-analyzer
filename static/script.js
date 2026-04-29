document.addEventListener("DOMContentLoaded", () => {
    // Character count with over-limit warning
    const textarea = document.getElementById("script_text");
    const charCount = document.getElementById("char-count");
    const overLimitWarn = document.getElementById("over-limit-warn");
    if (textarea && charCount) {
        textarea.addEventListener("input", () => {
            var len = textarea.value.length;
            charCount.textContent = len;
            if (len > 30000) {
                charCount.style.color = "var(--error)";
                if (overLimitWarn) overLimitWarn.style.display = "inline";
            } else {
                charCount.style.color = "";
                if (overLimitWarn) overLimitWarn.style.display = "none";
            }
        });
    }

    // Example script button
    var exampleBtn = document.getElementById("example-btn");
    if (exampleBtn && textarea) {
        exampleBtn.addEventListener("click", () => {
            textarea.value = EXAMPLE_SCRIPT.trim();
            textarea.dispatchEvent(new Event("input"));
            textarea.scrollIntoView({ behavior: "smooth" });
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

    // Prompt reference panel — toggle
    const refToggle = document.getElementById("prompt-ref-toggle");
    const refPanel = refToggle ? refToggle.parentElement : null;
    if (refToggle && refPanel) {
        refToggle.addEventListener("click", () => {
            refPanel.classList.toggle("open");
        });
    }

    // Prompt tag click — copy Chinese text
    document.querySelectorAll(".prompt-tag").forEach((tag) => {
        tag.addEventListener("click", () => {
            const zh = tag.getAttribute("data-zh");
            if (!zh) return;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(zh).then(() => {
                    tag.classList.add("copied");
                    setTimeout(() => tag.classList.remove("copied"), 800);
                });
            } else {
                const ta = document.createElement("textarea");
                ta.value = zh;
                ta.style.position = "fixed";
                ta.style.opacity = "0";
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
                tag.classList.add("copied");
                setTimeout(() => tag.classList.remove("copied"), 800);
            }
        });
    });
});

// Example short drama script
var EXAMPLE_SCRIPT = "第一集 1-1 夜 内 办公室\n人物：林然，陈总\n△林然独自在工位上加班，电脑屏幕的光映在她疲惫的脸上。陈总醉醺醺地走进来，把一叠文件甩在林然桌上。\n陈总（冷笑）：方案我看了，垃圾。明天拿不出新方案，滚蛋。\n△陈总转身离开。林然低着头，手指攥紧鼠标。\n林然OS：忍。等我拿下蓝天项目，第一个走的是你。\n\n1-2 夜 内 林然家\n人物：林然，苏晴\n△林然拖着疲惫的身体推开门，闺蜜苏晴从沙发上跳起来。\n苏晴（兴奋）：然然！蓝天集团发来邮件了，他们想约你明天面谈！\n△林然愣住，随即眼眶泛红。\n林然：真的？\n苏晴：因为陈凯那种人哭？不值得！你的方案明明是你一个人做的，他抢你功劳这么多年，该还了！\n林然（擦掉眼泪，眼神变坚定）：你说得对。明天，我要让所有人知道真相。\n\n第一集完\n\n第二集 2-1 日 内 蓝天集团会议室\n人物：林然，陈总，蓝天集团王总监，三个路人\n△林然走进会议室，发现陈总也在场，正满脸堆笑地和王总监寒暄。\n陈总（对王总监）：我们团队在林然同事的协助下，为这个项目熬了整整一个月。\n△林然深吸一口气，从包里拿出一个U盘。\n林然：王总监，我这里有项目原始文件的创建记录和时间戳。这个方案从头到尾是我一个人的。陈总只是在我完成后，把封面上的名字改成了他自己。\n陈总（脸色铁青）：你胡说八道！\n林然：需要我打开版本历史给大家看看吗？\n△王总监接过U盘，看了看陈总，又看了看林然。\n王总监：有意思。林小姐，你愿不愿意直接来蓝天集团？我们缺你这样的人。\n△林然微微一笑，瞥了眼陈总惨白的脸。\n林然：我愿意。\n林然OS：谢谢你，陈总。是你教会了我——善良不是忍让，是时候反击了。\n\n第二集完";
