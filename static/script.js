document.addEventListener("DOMContentLoaded", () => {
    // ============================================================
    // AI NEURAL NETWORK BACKGROUND
    // ============================================================
    const canvas = document.getElementById("ai-bg-canvas");
    if (canvas) {
        // Respect reduced-motion preference
        const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (prefersReducedMotion) {
            canvas.style.display = "none";
        } else {
            const ctx = canvas.getContext("2d");
            let W, H, dpr;

            function resize() {
                dpr = Math.min(window.devicePixelRatio || 1, 2);
                W = canvas.width = window.innerWidth * dpr;
                H = canvas.height = window.innerHeight * dpr;
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            }
            resize();
            window.addEventListener("resize", resize);

            const cssW = () => W / dpr;
            const cssH = () => H / dpr;

            // ---- Neuron Node ----
            class Neuron {
                constructor() {
                    this.reset(true);
                }
                reset(init) {
                    const w = cssW(), h = cssH();
                    this.x = init ? Math.random() * w : (Math.random() < 0.5 ? -40 : w + 40);
                    this.y = init ? Math.random() * h : Math.random() * h;
                    this.r = 1.2 + Math.random() * 2.2;
                    this.vx = (Math.random() - 0.5) * 0.30;
                    this.vy = (Math.random() - 0.5) * 0.25;
                    this.alpha = 0.25 + Math.random() * 0.45;
                    this.pulsePhase = Math.random() * Math.PI * 2;
                    this.pulseSpeed = 0.3 + Math.random() * 1.2;
                    this.pulseStrength = 0.4 + Math.random() * 0.6;
                }
                update(dt) {
                    const w = cssW(), h = cssH();
                    this.x += this.vx * dt;
                    this.y += this.vy * dt;
                    // Wrap around edges with margin
                    if (this.x < -20) this.x = w + 20;
                    if (this.x > w + 20) this.x = -20;
                    if (this.y < -20) this.y = h + 20;
                    if (this.y > h + 20) this.y = -20;
                }
                draw(ctx, t) {
                    const pulse = 1 + Math.sin(t * this.pulseSpeed + this.pulsePhase) * this.pulseStrength * 0.35;
                    const r = this.r * pulse;
                    const a = this.alpha * (0.7 + 0.3 * pulse);
                    // Core
                    ctx.fillStyle = `rgba(165,180,252,${a})`;
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, r, 0, Math.PI * 2);
                    ctx.fill();
                    // Glow halo
                    ctx.fillStyle = `rgba(129,140,248,${a * 0.3})`;
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, r * 2.5, 0, Math.PI * 2);
                    ctx.fill();
                }
            }

            // ---- Fewer neurons on small screens ----
            const isMobile = cssW() < 768;
            const neuronCount = isMobile ? 20 : 45;
            const CONNECTION_DIST = 150;
            const neurons = Array.from({ length: neuronCount }, () => new Neuron());
            let time = 0;
            let lastFrame = performance.now();
            let animFrameId = null;
            let paused = false;

            // Pause when tab is hidden
            document.addEventListener("visibilitychange", () => {
                if (document.hidden) {
                    paused = true;
                    lastFrame = 0; // forces dt reset on resume
                } else {
                    paused = false;
                    lastFrame = 0;
                    animFrameId = requestAnimationFrame(animate);
                }
            });

            function animate(now) {
                if (paused) return;
                let dt = now - lastFrame;
                lastFrame = now;
                if (dt > 80 || dt <= 0) dt = 16; // cap to avoid jump on tab switch
                time += dt * 0.001;

                ctx.clearRect(0, 0, cssW(), cssH());

                // Update neurons
                neurons.forEach(n => n.update(dt));

                // Draw connections between nearby neurons
                for (let i = 0; i < neurons.length; i++) {
                    for (let j = i + 1; j < neurons.length; j++) {
                        const dx = neurons[i].x - neurons[j].x;
                        const dy = neurons[i].y - neurons[j].y;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < CONNECTION_DIST) {
                            const lineAlpha = (1 - dist / CONNECTION_DIST) * 0.12;
                            ctx.strokeStyle = `rgba(129,140,248,${lineAlpha})`;
                            ctx.lineWidth = 0.6;
                            ctx.beginPath();
                            ctx.moveTo(neurons[i].x, neurons[i].y);
                            ctx.lineTo(neurons[j].x, neurons[j].y);
                            ctx.stroke();
                        }
                    }
                }

                // Draw neurons on top
                neurons.forEach(n => n.draw(ctx, time));

                animFrameId = requestAnimationFrame(animate);
            }
            requestAnimationFrame(animate);
        }
    }

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

    // (prompt builder moved to Prompt Studio page)

    // ============================================================
    // DASHBOARD V2 — ECharts + stats
    // ============================================================
    initDashboard();
});

// Example short drama script
var EXAMPLE_SCRIPT = "第一集 1-1 夜 内 办公室\n人物：林然，陈总\n△林然独自在工位上加班，电脑屏幕的光映在她疲惫的脸上。陈总醉醺醺地走进来，把一叠文件甩在林然桌上。\n陈总（冷笑）：方案我看了，垃圾。明天拿不出新方案，滚蛋。\n△陈总转身离开。林然低着头，手指攥紧鼠标。\n林然OS：忍。等我拿下蓝天项目，第一个走的是你。\n\n1-2 夜 内 林然家\n人物：林然，苏晴\n△林然拖着疲惫的身体推开门，闺蜜苏晴从沙发上跳起来。\n苏晴（兴奋）：然然！蓝天集团发来邮件了，他们想约你明天面谈！\n△林然愣住，随即眼眶泛红。\n林然：真的？\n苏晴：因为陈凯那种人哭？不值得！你的方案明明是你一个人做的，他抢你功劳这么多年，该还了！\n林然（擦掉眼泪，眼神变坚定）：你说得对。明天，我要让所有人知道真相。\n\n第一集完\n\n第二集 2-1 日 内 蓝天集团会议室\n人物：林然，陈总，蓝天集团王总监，三个路人\n△林然走进会议室，发现陈总也在场，正满脸堆笑地和王总监寒暄。\n陈总（对王总监）：我们团队在林然同事的协助下，为这个项目熬了整整一个月。\n△林然深吸一口气，从包里拿出一个U盘。\n林然：王总监，我这里有项目原始文件的创建记录和时间戳。这个方案从头到尾是我一个人的。陈总只是在我完成后，把封面上的名字改成了他自己。\n陈总（脸色铁青）：你胡说八道！\n林然：需要我打开版本历史给大家看看吗？\n△王总监接过U盘，看了看陈总，又看了看林然。\n王总监：有意思。林小姐，你愿不愿意直接来蓝天集团？我们缺你这样的人。\n△林然微微一笑，瞥了眼陈总惨白的脸。\n林然：我愿意。\n林然OS：谢谢你，陈总。是你教会了我——善良不是忍让，是时候反击了。\n\n第二集完";

// ============================================================
// DASHBOARD V2
// ============================================================
function initDashboard() {
    var kpiGrid = document.getElementById("dash-kpi-grid");
    if (!kpiGrid) return;

    var chartTrend = null;
    var chartType = null;
    var currentRange = "7";

    function fetchStats(range) {
        document.querySelectorAll(".dash-kpi-val").forEach(function(el) {
            el.classList.add("loading");
        });

        fetch("/api/dashboard/stats?range=" + range)
            .then(function(r) { return r.json(); })
            .then(function(d) {
                updateKPIs(d.kpis);
                renderTrend(d.trend);
                renderTypeDist(d.type_distribution);
            })
            .catch(function() {
                document.querySelectorAll(".dash-kpi-val").forEach(function(el) {
                    el.classList.remove("loading");
                    el.textContent = "-";
                });
            });
    }

    function updateKPIs(kpis) {
        document.querySelectorAll(".dash-kpi-val").forEach(function(el) {
            el.classList.remove("loading");
        });
        document.getElementById("kpi-credits").textContent = kpis.credits;
        document.getElementById("kpi-analyses").textContent = kpis.total_analyses;
        document.getElementById("kpi-spent").textContent = kpis.total_spent;
        document.getElementById("kpi-earned").textContent = kpis.total_earned;
    }

    function getChartColors() {
        var s = getComputedStyle(document.documentElement);
        return {
            accent: s.getPropertyValue("--accent").trim() || "#818cf8",
            accentLight: s.getPropertyValue("--accent-light").trim() || "#a5b4fc",
            success: s.getPropertyValue("--success").trim() || "#34d399",
            error: s.getPropertyValue("--error").trim() || "#f87171",
            warning: s.getPropertyValue("--warning").trim() || "#fbbf24",
            textSecondary: s.getPropertyValue("--text-secondary").trim() || "#9494a4",
            textMuted: s.getPropertyValue("--text-muted").trim() || "#5c5c6e",
            border: s.getPropertyValue("--border").trim() || "#1e1e2e",
            cardBg: s.getPropertyValue("--card-bg").trim() || "#16161f"
        };
    }

    function renderTrend(data) {
        var el = document.getElementById("chart-trend");
        if (!el) return;

        if (!chartTrend) {
            chartTrend = echarts.init(el);
        }

        var c = getChartColors();
        var dates = data.map(function(d) { return d.date; });
        var spent = data.map(function(d) { return d.spent; });
        var earned = data.map(function(d) { return d.earned; });

        chartTrend.setOption({
            color: [c.error, c.success],
            tooltip: {
                trigger: "axis",
                backgroundColor: c.cardBg,
                borderColor: c.border,
                textStyle: { color: c.textSecondary, fontSize: 12 }
            },
            legend: {
                bottom: 0,
                textStyle: { color: c.textMuted, fontSize: 12 },
                data: ["消费", "获取"],
                itemGap: 20
            },
            grid: { left: 16, right: 24, top: 20, bottom: 40 },
            xAxis: {
                type: "category",
                data: dates,
                axisLine: { lineStyle: { color: c.border } },
                axisTick: { show: false },
                axisLabel: { color: c.textMuted, fontSize: 11 }
            },
            yAxis: {
                type: "value",
                splitLine: { lineStyle: { color: c.border, type: "dashed" } },
                axisLabel: { color: c.textMuted, fontSize: 11 }
            },
            series: [
                {
                    name: "消费",
                    type: "line",
                    data: spent,
                    smooth: true,
                    symbol: "circle",
                    symbolSize: 4,
                    lineStyle: { width: 2 },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: "rgba(248,113,113,0.15)" },
                            { offset: 1, color: "rgba(248,113,113,0.0)" }
                        ])
                    }
                },
                {
                    name: "获取",
                    type: "line",
                    data: earned,
                    smooth: true,
                    symbol: "circle",
                    symbolSize: 4,
                    lineStyle: { width: 2 },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: "rgba(52,211,153,0.15)" },
                            { offset: 1, color: "rgba(52,211,153,0.0)" }
                        ])
                    }
                }
            ]
        }, true);
    }

    function renderTypeDist(data) {
        var el = document.getElementById("chart-type");
        if (!el) return;

        if (!chartType) {
            chartType = echarts.init(el);
        }

        var c = getChartColors();
        var pieColors = [c.accent, c.success, c.warning, c.accentLight, c.error];

        chartType.setOption({
            color: pieColors,
            tooltip: {
                trigger: "item",
                backgroundColor: c.cardBg,
                borderColor: c.border,
                textStyle: { color: c.textSecondary, fontSize: 12 },
                formatter: "{b}: {c} 次 ({d}%)"
            },
            legend: {
                bottom: 0,
                textStyle: { color: c.textMuted, fontSize: 12 },
                itemGap: 16
            },
            series: [{
                type: "pie",
                radius: ["50%", "78%"],
                center: ["50%", "48%"],
                avoidLabelOverlap: false,
                itemStyle: {
                    borderColor: c.cardBg,
                    borderWidth: 3,
                    borderRadius: 4
                },
                label: { show: false },
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 14,
                        fontWeight: "bold",
                        color: c.textSecondary
                    },
                    scaleSize: 8
                },
                data: data
            }]
        }, true);
    }

    // Time-range tabs
    var rangeTabs = document.getElementById("range-tabs");
    if (rangeTabs) {
        rangeTabs.addEventListener("click", function(e) {
            var btn = e.target.closest(".dash-range-btn");
            if (!btn) return;
            var range = btn.dataset.range;
            if (range === currentRange) return;
            currentRange = range;

            rangeTabs.querySelectorAll(".dash-range-btn").forEach(function(b) {
                b.classList.remove("active");
            });
            btn.classList.add("active");

            fetchStats(range);
        });
    }

    fetchStats("7");

    window.addEventListener("resize", function() {
        if (chartTrend) chartTrend.resize();
        if (chartType) chartType.resize();
    });
}
