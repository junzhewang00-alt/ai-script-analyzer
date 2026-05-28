# Design System: AI Script Analyzer

## 1. Visual Theme & Atmosphere

A modern studio workspace for writers — quiet, focused, and slightly warm. The interface
feels like a professional writing room at dusk: deep charcoal walls, soft ambient light,
and one clear accent color drawing attention to action. No cinematic gimmicks, no film
grain — just clean surfaces and thoughtful spacing that let the content breathe.

**Key Characteristics:**
- Deep charcoal canvas (`#0b0b0f`) as foundation, not pure black
- Indigo accent (`#818cf8`) for primary actions — calm, creative, un-techy
- Clean geometric background: subtle radial gradient, optional faint dot-grid
- Generous whitespace with editorial pacing
- Soft card shadows (`rgba(0,0,0,0.2) 0px 2px 16px`) instead of heavy borders
- Single font family with clear weight hierarchy — no serif/sans split

## 2. Color Palette & Roles

### Surface & Background
| Token | Value | Role |
|-------|-------|------|
| bg-deep | `#0b0b0f` | Page background |
| bg | `#111118` | Elevated surfaces |
| card-bg | `#16161f` | Cards, panels |
| card-bg-hover | `#1c1c28` | Card hover |
| input-bg | `#0f0f17` | Inputs, textareas |
| border | `#1e1e2e` | Standard border |
| border-light | `#2a2a3e` | Emphasized border |

### Text
| Token | Value | Role |
|-------|-------|------|
| text-primary | `#e4e4ec` | Primary text |
| text-secondary | `#9494a4` | Secondary text |
| text-muted | `#5c5c6e` | Tertiary/muted text |

### Accent
| Token | Value | Role |
|-------|-------|------|
| accent | `#818cf8` | Primary accent (indigo) |
| accent-light | `#a5b4fc` | Hover/light accent |
| accent-dark | `#6366f1` | Pressed/deep accent |
| accent-glow | `rgba(129,140,248,0.12)` | Glow/focus ring |
| accent-glow-strong | `rgba(129,140,248,0.25)` | Strong glow |

### Semantic
| Token | Value | Role |
|-------|-------|------|
| success | `#34d399` | Success green |
| error | `#f87171` | Error red |
| error-bg | `rgba(248,113,113,0.08)` | Error background |
| warning | `#fbbf24` | Warning amber |
| warning-bg | `rgba(251,191,36,0.08)` | Warning background |

## 3. Typography Rules

### Font Family
- **Primary**: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif`
- **Mono**: `"Cascadia Code", "SF Mono", "Fira Code", "Consolas", monospace`

### Hierarchy
| Role | Size | Weight | Line Height | Notes |
|------|------|--------|-------------|-------|
| Hero | 2rem (32px) | 700 | 1.3 | Page title |
| Section heading | 1.25rem (20px) | 700 | 1.4 | Card/section titles |
| Sub-heading | 1.05rem (17px) | 600 | 1.5 | Sub-titles |
| Body | 0.95rem (15px) | 400 | 1.7 | Main body text |
| Label | 0.85rem (14px) | 600 | 1.4 | Form labels |
| Caption | 0.78rem (12px) | 400 | 1.5 | Metadata |
| Code | 0.88rem (14px) | 400 | 1.7 | Monospace content |

### Principles
- Single font family — hierarchy through size and weight, not typeface shifts
- Generous line-height (1.7) for body text — comfortable reading for long scripts
- Weight 600-700 for headings, 400 for body — clean contrast without heaviness

## 4. Component Stylings

### Buttons
**Primary (Accent)**
- Background: `linear-gradient(135deg, #6366f1, #818cf8)`
- Text: `#ffffff`
- Radius: 8px, padding: 13px 28px
- Hover: brighter gradient + glow shadow

**Outline**
- Background: transparent
- Text: accent, border: 1px solid rgba accent
- Radius: 8px, padding: 8px 18px

### Cards
- Background: card-bg (`#16161f`)
- Border: 1px solid border (`#1e1e2e`)
- Radius: 12px (standard), 16px (large)
- Shadow: `rgba(0,0,0,0.2) 0px 2px 16px`

### Inputs
- Background: input-bg (`#0f0f17`)
- Border: 1px solid border
- Radius: 8px
- Focus: accent border + glow ring

## 5. Layout Principles
- Max container width: 920px, centered
- Base spacing unit: 8px
- Section spacing: 48px-72px
- Card padding: 32-40px

## 6. Depth & Elevation
| Level | Treatment | Use |
|-------|-----------|-----|
| Flat | No shadow | Page background |
| Raised | `0px 2px 16px rgba(0,0,0,0.2)` | Cards |
| Elevated | `0px 4px 24px rgba(0,0,0,0.3)` | Modals, dropdowns |
| Focus | `0px 0px 0px 3px accent-glow` | Input focus |

## 7. Do's and Don'ts
- Do use the indigo accent sparingly — one CTA per view
- Do keep backgrounds deep charcoal, never pure black
- Do maintain generous body line-height (1.7)
- Don't use film-grain or heavy texture overlays
- Don't introduce additional accent colors beyond indigo
- Don't use serif fonts — the sans-serif hierarchy is intentional

## 8. Responsive Behavior
| Breakpoint | Key Changes |
|------------|-------------|
| <640px | Single column, reduced padding, smaller headings |
| 640-768px | 2-column grids begin |
| 768px+ | Full layout, maximum spacing |

## 9. Agent Prompt Guide
- Page background: `bg-deep` (#0b0b0f)
- Cards: `card-bg` (#16161f) with 1px solid border
- Primary CTA: indigo gradient button
- Text hierarchy: weight 700/600/400 at sizes above
- No texture overlays, no serif fonts, no gold
