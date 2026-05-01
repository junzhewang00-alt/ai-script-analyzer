document.addEventListener("DOMContentLoaded", () => {
    // ============================================================
    // ENHANCED DYNAMIC CINEMATIC BACKGROUND
    // ============================================================
    const canvas = document.getElementById("bg-canvas");
    if (canvas) {
        const ctx = canvas.getContext("2d");
        let W, H, dpr;
        let mouseX = 0.5, mouseY = 0.5;
        let targetMouseX = 0.5, targetMouseY = 0.5;
        let time = 0;
        let scrollY = 0;
        let targetScrollY = 0;

        function resize() {
            dpr = Math.min(window.devicePixelRatio || 1, 2);
            W = canvas.width = window.innerWidth * dpr;
            H = canvas.height = window.innerHeight * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        resize();
        window.addEventListener("resize", resize);

        const CSS_W = () => W / dpr;
        const CSS_H = () => H / dpr;

        document.addEventListener("mousemove", (e) => {
            targetMouseX = e.clientX / CSS_W();
            targetMouseY = e.clientY / CSS_H();
        });
        window.addEventListener("scroll", () => {
            targetScrollY = window.scrollY;
        });

        // ---- Star: deep-field twinkling background stars ----
        class Star {
            constructor() {
                this.x = Math.random() * 3000;
                this.y = Math.random() * 3000;
                this.r = 0.4 + Math.random() * 1.4;
                this.depth = 0.2 + Math.random() * 0.8;
                this.twinklePhase = Math.random() * Math.PI * 2;
                this.twinkleSpeed = 0.5 + Math.random() * 2.0;
                this.hue = Math.random() < 0.7 ? 40 + Math.random() * 20 : 200 + Math.random() * 40;
            }
            draw(ctx, t) {
                const twinkle = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * this.twinkleSpeed + this.twinklePhase));
                const a = this.depth * twinkle * 1.0;
                const px = this.x % CSS_W();
                const py = this.y % CSS_H();
                ctx.fillStyle = `hsla(${this.hue}, 60%, 70%, ${a})`;
                ctx.beginPath();
                ctx.arc(px, py, this.r, 0, Math.PI * 2);
                ctx.fill();
                // Glow halo for brighter stars
                if (this.r > 0.7 && twinkle > 0.8) {
                    ctx.fillStyle = `hsla(${this.hue}, 80%, 75%, ${a * 0.3})`;
                    ctx.beginPath();
                    ctx.arc(px, py, this.r * 3, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        }

        // ---- Blob: slow-moving morphing gradient orbs ----
        class Blob {
            constructor() {
                this.reset(true);
            }
            reset(init) {
                const w = CSS_W(), h = CSS_H();
                this.x = init ? Math.random() * w : (Math.random() < 0.5 ? -200 : w + 200);
                this.y = Math.random() * h;
                this.r = 100 + Math.random() * 300;
                this.vx = (Math.random() - 0.5) * 0.2;
                this.vy = (Math.random() - 0.5) * 0.15;
                this.hue = 30 + Math.random() * 30;
                if (Math.random() < 0.25) this.hue = 210 + Math.random() * 30;
                if (Math.random() < 0.15) this.hue = 280 + Math.random() * 20;
                this.alpha = 0.05 + Math.random() * 0.10;
                this.phase = Math.random() * Math.PI * 2;
                this.morphFreq = 0.2 + Math.random() * 0.5;
                this.morphAmp = 0.5 + Math.random() * 0.5;
                this.depth = 0.3 + Math.random() * 0.7;
            }
            update(dt) {
                const w = CSS_W(), h = CSS_H();
                const parallax = this.depth * 0.5;
                this.x += this.vx * dt + (mouseX - 0.5) * parallax * 0.3;
                this.y += this.vy * dt + (mouseY - 0.5) * parallax * 0.3;
                this.vx += ((mouseX - 0.5) * 0.2 * parallax - this.vx) * 0.0003 * dt;
                this.vy += ((mouseY - 0.5) * 0.2 * parallax - this.vy) * 0.0003 * dt;
                if (this.x < -this.r) { this.x = w + this.r; this.y = Math.random() * h; }
                if (this.x > w + this.r) { this.x = -this.r; this.y = Math.random() * h; }
                if (this.y < -this.r) this.y = h + this.r;
                if (this.y > h + this.r) this.y = -this.r;
            }
            draw(ctx, t) {
                const morphX = Math.sin(t * this.morphFreq + this.phase) * this.morphAmp * this.r * 0.35;
                const morphY = Math.cos(t * this.morphFreq * 0.7 + this.phase + 1) * this.morphAmp * this.r * 0.3;
                const rx = this.r + morphX;
                const ry = this.r * 0.8 + morphY;
                const grad = ctx.createRadialGradient(this.x, this.y, 0, this.x, this.y, Math.max(rx, ry));
                grad.addColorStop(0, `hsla(${this.hue}, 65%, 55%, ${this.alpha * 1.6})`);
                grad.addColorStop(0.35, `hsla(${this.hue}, 50%, 35%, ${this.alpha})`);
                grad.addColorStop(0.7, `hsla(${this.hue}, 40%, 18%, ${this.alpha * 0.25})`);
                grad.addColorStop(1, "transparent");
                ctx.save();
                ctx.translate(this.x, this.y);
                ctx.scale(rx / this.r, ry / this.r);
                ctx.fillStyle = grad;
                ctx.beginPath();
                ctx.arc(0, 0, this.r, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();
            }
        }

        // ---- Particle: floating dust with connection networking ----
        class Particle {
            constructor() { this.reset(true); }
            reset(init) {
                const w = CSS_W(), h = CSS_H();
                this.x = init ? Math.random() * w : Math.random() * w;
                this.y = init ? Math.random() * h : h + 10;
                this.r = 0.3 + Math.random() * 1.2;
                this.vx = (Math.random() - 0.5) * 0.4;
                this.vy = -(0.1 + Math.random() * 0.6);
                this.alpha = 0.18 + Math.random() * 0.50;
                this.alphaVar = Math.random() * Math.PI * 2;
                this.life = 0;
                this.maxLife = 300 + Math.random() * 800;
                this.hue = Math.random() < 0.85 ? 38 + Math.random() * 15 : 200 + Math.random() * 30;
            }
            update(dt) {
                const w = CSS_W(), h = CSS_H();
                this.life += dt;
                if (this.life > this.maxLife) this.reset(false);
                this.x += this.vx * dt + Math.sin(this.life * 0.003 + this.alphaVar) * 0.05 * dt;
                this.y += this.vy * dt;
                // Gentle mouse attraction on nearby particles
                const dx = mouseX * w - this.x;
                const dy = mouseY * h - this.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 250 && dist > 0) {
                    this.x += (dx / dist) * 0.3 * dt;
                    this.y += (dy / dist) * 0.3 * dt;
                }
                if (this.y < -10 || this.x < -10 || this.x > w + 10) this.reset(false);
            }
            draw(ctx) {
                const flicker = 0.4 + 0.6 * Math.sin(this.alphaVar + this.life * 0.025);
                const a = this.alpha * flicker;
                ctx.fillStyle = `hsla(${this.hue}, 50%, 70%, ${a})`;
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        // ---- Energy Ripple: expanding ring bursts ----
        class Ripple {
            constructor() {
                this.reset();
            }
            reset() {
                const w = CSS_W(), h = CSS_H();
                this.x = Math.random() * w;
                this.y = Math.random() * h;
                this.radius = 0;
                this.maxRadius = 200 + Math.random() * 400;
                this.speed = 0.3 + Math.random() * 0.7;
                this.alpha = 0;
                this.maxAlpha = 0.10 + Math.random() * 0.12;
                this.life = 0;
                this.delay = Math.random() * 6;
            }
            update(dt) {
                this.life += dt * 0.001;
                if (this.life < this.delay) return;
                const active = this.life - this.delay;
                this.radius = active * this.speed * 150;
                const progress = this.radius / this.maxRadius;
                if (progress > 1) { this.reset(); this.life = 0; return; }
                this.alpha = this.maxAlpha * (1 - progress) * Math.sin(progress * Math.PI);
            }
            draw(ctx) {
                if (this.alpha < 0.001) return;
                ctx.strokeStyle = `rgba(200,163,78,${this.alpha})`;
                ctx.lineWidth = 0.5;
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.stroke();
            }
        }

        // ---- Cursor Glow ----
        let glowAlpha = 0, targetGlowAlpha = 0;
        function drawCursorGlow(ctx) {
            const w = CSS_W(), h = CSS_H();
            const mx = mouseX * w, my = mouseY * h;
            targetGlowAlpha = 0.14;
            glowAlpha += (targetGlowAlpha - glowAlpha) * 0.05;
            if (glowAlpha < 0.002) return;
            const grad = ctx.createRadialGradient(mx, my, 0, mx, my, 280);
            grad.addColorStop(0, `rgba(220,180,100,${glowAlpha})`);
            grad.addColorStop(0.5, `rgba(180,140,60,${glowAlpha * 0.4})`);
            grad.addColorStop(1, "transparent");
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.arc(mx, my, 280, 0, Math.PI * 2);
            ctx.fill();
        }

        // ---- Initialize ----
        const stars = Array.from({ length: 180 }, () => new Star());
        const blobs = Array.from({ length: 8 }, () => new Blob());
        const particles = Array.from({ length: 120 }, () => new Particle());
        const ripples = Array.from({ length: 4 }, () => new Ripple());

        let lastFrame = performance.now();

        function animate(now) {
            let dt = now - lastFrame;
            lastFrame = now;
            if (dt > 100) dt = 16;
            time += dt * 0.001;
            scrollY += (targetScrollY - scrollY) * 0.05;

            mouseX += (targetMouseX - mouseX) * 0.03 * (dt / 16);
            mouseY += (targetMouseY - mouseY) * 0.03 * (dt / 16);

            ctx.clearRect(0, 0, CSS_W(), CSS_H());

            // Layer 1: deep starfield
            stars.forEach(s => s.draw(ctx, time));

            // Layer 2: energy ripples
            ripples.forEach(r => { r.update(dt); r.draw(ctx); });

            // Layer 3: blobs
            blobs.forEach(b => { b.update(dt); b.draw(ctx, time); });

            // Layer 4: particle network (draw connections then particles)
            const MAX_DIST = 110;
            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < MAX_DIST) {
                        const alpha = (1 - dist / MAX_DIST) * 0.18;
                        ctx.strokeStyle = `rgba(200,163,78,${alpha})`;
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.stroke();
                    }
                }
            }
            particles.forEach(p => { p.update(dt); p.draw(ctx); });

            // Layer 5: cursor glow (topmost atmospheric layer)
            drawCursorGlow(ctx);

            requestAnimationFrame(animate);
        }

        requestAnimationFrame(animate);
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
});

// Example short drama script
var EXAMPLE_SCRIPT = "第一集 1-1 夜 内 办公室\n人物：林然，陈总\n△林然独自在工位上加班，电脑屏幕的光映在她疲惫的脸上。陈总醉醺醺地走进来，把一叠文件甩在林然桌上。\n陈总（冷笑）：方案我看了，垃圾。明天拿不出新方案，滚蛋。\n△陈总转身离开。林然低着头，手指攥紧鼠标。\n林然OS：忍。等我拿下蓝天项目，第一个走的是你。\n\n1-2 夜 内 林然家\n人物：林然，苏晴\n△林然拖着疲惫的身体推开门，闺蜜苏晴从沙发上跳起来。\n苏晴（兴奋）：然然！蓝天集团发来邮件了，他们想约你明天面谈！\n△林然愣住，随即眼眶泛红。\n林然：真的？\n苏晴：因为陈凯那种人哭？不值得！你的方案明明是你一个人做的，他抢你功劳这么多年，该还了！\n林然（擦掉眼泪，眼神变坚定）：你说得对。明天，我要让所有人知道真相。\n\n第一集完\n\n第二集 2-1 日 内 蓝天集团会议室\n人物：林然，陈总，蓝天集团王总监，三个路人\n△林然走进会议室，发现陈总也在场，正满脸堆笑地和王总监寒暄。\n陈总（对王总监）：我们团队在林然同事的协助下，为这个项目熬了整整一个月。\n△林然深吸一口气，从包里拿出一个U盘。\n林然：王总监，我这里有项目原始文件的创建记录和时间戳。这个方案从头到尾是我一个人的。陈总只是在我完成后，把封面上的名字改成了他自己。\n陈总（脸色铁青）：你胡说八道！\n林然：需要我打开版本历史给大家看看吗？\n△王总监接过U盘，看了看陈总，又看了看林然。\n王总监：有意思。林小姐，你愿不愿意直接来蓝天集团？我们缺你这样的人。\n△林然微微一笑，瞥了眼陈总惨白的脸。\n林然：我愿意。\n林然OS：谢谢你，陈总。是你教会了我——善良不是忍让，是时候反击了。\n\n第二集完";
