// config.js — AMALYN Network Configuration & Shared UI Engine
// This file is loaded by all portals to detect the right API URL, manage themes, and power ambient particles

const AMALYN_CONFIG = (() => {
    const hostname = location.hostname;

    // Running locally
    const isLocal = hostname === 'localhost' ||
                    hostname === '127.0.0.1' ||
                    hostname.startsWith('192.168') ||
                    hostname.startsWith('10.') ||
                    hostname === '';

    const LOCAL_IP = '192.168.1.100';
    const LOCAL_PORT = '8000';
    const RENDER_API = 'https://amalyn-tech.onrender.com';

    let apiUrl, wsUrl;

    if (location.protocol === 'file:') {
        apiUrl = `http://localhost:${LOCAL_PORT}`;
        wsUrl = `ws://localhost:${LOCAL_PORT}/ws`;
    } else if (isLocal) {
        apiUrl = `http://${hostname}:${LOCAL_PORT}`;
        wsUrl = `ws://${hostname}:${LOCAL_PORT}/ws`;
    } else {
        apiUrl = RENDER_API;
        wsUrl = `ws://localhost:${LOCAL_PORT}/ws`;
    }

    // --- THEME MANAGEMENT ---
    function getStoredTheme() {
        return localStorage.getItem('amalyn_theme') || 'dark';
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('amalyn_theme', theme);
        document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
            btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
            btn.innerHTML = theme === 'dark'
                ? '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
                : '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>';
            btn.title = theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
        });
        window.dispatchEvent(new CustomEvent('amalyn-theme-change', { detail: { theme } }));
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || getStoredTheme();
        const next = current === 'dark' ? 'light' : 'dark';
        setTheme(next);
        return next;
    }

    function initTheme() {
        const theme = getStoredTheme();
        document.documentElement.setAttribute('data-theme', theme);
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => setTheme(theme));
        } else {
            setTheme(theme);
        }
    }

    // Initialize theme immediately to prevent flash of wrong theme
    initTheme();

    // --- HIGH-PERFORMANCE AMBIENT PARTICLE ENGINE ---
    function initParticleCanvas(canvasId = 'ambient-particles') {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;

        const ctx = canvas.getContext('2d');
        if (!ctx) return null;

        let width = 0, height = 0;
        let animationFrame = null;
        let isVisible = !document.hidden;
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        const mouse = { x: -1000, y: -1000, radius: 120 };

        function resize() {
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            width = window.innerWidth;
            height = window.innerHeight;
            canvas.width = Math.round(width * dpr);
            canvas.height = Math.round(height * dpr);
            canvas.style.width = width + 'px';
            canvas.style.height = height + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }

        window.addEventListener('resize', resize, { passive: true });
        resize();

        window.addEventListener('pointermove', (e) => {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        }, { passive: true });

        window.addEventListener('pointerleave', () => {
            mouse.x = -1000;
            mouse.y = -1000;
        }, { passive: true });

        document.addEventListener('visibilitychange', () => {
            isVisible = !document.hidden;
            if (isVisible && !animationFrame && !prefersReducedMotion) {
                animationFrame = requestAnimationFrame(animate);
            }
        });

        // 35 particles is the sweet spot: silky 60fps, 0 lag, rich ambience
        const particleCount = prefersReducedMotion ? 0 : Math.min(38, Math.floor((width * height) / 32000));
        const particles = [];

        for (let i = 0; i < particleCount; i++) {
            particles.push({
                x: Math.random() * width,
                y: Math.random() * height,
                vx: (Math.random() - 0.5) * 0.45,
                vy: (Math.random() - 0.5) * 0.45,
                radius: Math.random() * 1.8 + 1.0,
                baseAlpha: Math.random() * 0.4 + 0.25,
            });
        }

        function animate() {
            if (!isVisible || prefersReducedMotion) {
                animationFrame = null;
                return;
            }

            ctx.clearRect(0, 0, width, height);

            const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
            const dotColor = isDark ? '123, 232, 255' : '43, 108, 176';
            const lineColor = isDark ? '75, 168, 255' : '99, 140, 195';

            for (let i = 0; i < particles.length; i++) {
                const p = particles[i];
                p.x += p.vx;
                p.y += p.vy;

                // Wrap around edges
                if (p.x < -10) p.x = width + 10;
                else if (p.x > width + 10) p.x = -10;
                if (p.y < -10) p.y = height + 10;
                else if (p.y > height + 10) p.y = -10;

                // Subtle mouse reaction
                const dx = mouse.x - p.x;
                const dy = mouse.y - p.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < mouse.radius && dist > 0) {
                    const force = (1 - dist / mouse.radius) * 0.7;
                    p.x -= (dx / dist) * force;
                    p.y -= (dy / dist) * force;
                }

                // Draw particle
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(${dotColor}, ${p.baseAlpha})`;
                ctx.fill();

                // Draw connections to nearby particles
                for (let j = i + 1; j < particles.length; j++) {
                    const p2 = particles[j];
                    const djx = p.x - p2.x;
                    const djy = p.y - p2.y;
                    const d = Math.sqrt(djx * djx + djy * djy);
                    if (d < 110) {
                        const alpha = (1 - d / 110) * (isDark ? 0.18 : 0.12);
                        ctx.beginPath();
                        ctx.strokeStyle = `rgba(${lineColor}, ${alpha})`;
                        ctx.lineWidth = 0.8;
                        ctx.moveTo(p.x, p.y);
                        ctx.lineTo(p2.x, p2.y);
                        ctx.stroke();
                    }
                }
            }

            animationFrame = requestAnimationFrame(animate);
        }

        if (!prefersReducedMotion) {
            animationFrame = requestAnimationFrame(animate);
        }

        return {
            destroy() {
                if (animationFrame) cancelAnimationFrame(animationFrame);
                window.removeEventListener('resize', resize);
            }
        };
    }

    return {
        apiUrl,
        wsUrl,
        isLocal,
        LOCAL_IP,
        LOCAL_PORT,
        RENDER_API,
        getStoredTheme,
        setTheme,
        toggleTheme,
        initTheme,
        initParticleCanvas
    };
})();

console.log('[AMALYN] Engine ready | API:', AMALYN_CONFIG.apiUrl, '| WS:', AMALYN_CONFIG.wsUrl);