---
name: Academic Precision
colors:
  surface: '#f9f9ff'
  surface-dim: '#d3daef'
  surface-bright: '#f9f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f1f3ff'
  surface-container: '#e9edff'
  surface-container-high: '#e1e8fd'
  surface-container-highest: '#dce2f7'
  on-surface: '#141b2b'
  on-surface-variant: '#43474e'
  inverse-surface: '#293040'
  inverse-on-surface: '#edf0ff'
  outline: '#74777f'
  outline-variant: '#c4c6cf'
  surface-tint: '#485f82'
  primary: '#00152f'
  on-primary: '#ffffff'
  primary-container: '#0f2a4a'
  on-primary-container: '#7a92b7'
  inverse-primary: '#b0c8f0'
  secondary: '#1d4ed8'
  on-secondary: '#ffffff'
  secondary-container: '#4069f2'
  on-secondary-container: '#fffbff'
  tertiary: '#00190e'
  on-tertiary: '#ffffff'
  tertiary-container: '#00301f'
  on-tertiary-container: '#24a375'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d4e3ff'
  primary-fixed-dim: '#b0c8f0'
  on-primary-fixed: '#001c3a'
  on-primary-fixed-variant: '#304869'
  secondary-fixed: '#dce1ff'
  secondary-fixed-dim: '#b7c4ff'
  on-secondary-fixed: '#001551'
  on-secondary-fixed-variant: '#0039b5'
  tertiary-fixed: '#85f8c4'
  tertiary-fixed-dim: '#68dba9'
  on-tertiary-fixed: '#002114'
  on-tertiary-fixed-variant: '#005137'
  background: '#f9f9ff'
  on-background: '#141b2b'
  surface-variant: '#dce2f7'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
  tabular-marks:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
  tabular-code:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-dense: 0.5rem
  margin: 1.5rem
  margin-mobile: 0.75rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style
The design system is crafted for high-stakes academic paper evaluation. Examiners and faculty members review dense, unstructured, and often messy handwritten manuscripts for hours at a time. The interface must serve as quiet, invisible infrastructure: zero visual noise, zero gratuitous flourishes, and zero emotional fatigue.

The aesthetic marries clinical typographic efficiency with the tactile dignity of classical scholarship. It leans into structured utilitarian minimalism—drawing inspiration from precision workbench software, archival typography, and rigorous editorial layouts.

### Emotional Objectives
- **Cognitive Serenity:** The interface never competes with the evaluated document. Surfaces remain calm, warm, and static.
- **Institutional Authority:** Visual elements communicate exactitude, fairness, and systematic verification through strict geometry and rigorous alignment.
- **Frictionless Density:** Information density is applied deliberately—high density in data grids, rubrics, and marking panels; generous spatial focus around the digital manuscript canvas.

## Colors
The palette avoids decorative gradients, artificial neon glows, and saturated purples. It relies strictly on an ink-on-parchment paradigm calibrated for extended screen exposure under varying office and study lighting conditions.

### Base & Structural Tones
- **Canvas Ground (`#F8F9FA`):** A warm off-white that reduces glare across broad monitors compared to sterile stark white.
- **Surface Elevation (`#FFFFFF`):** Reserved strictly for active document panes, data tables, sheets, and modal panels.
- **Subtle Perimeter Border (`#E5E7EB`):** A hairline divider used consistently across all modular zones.
- **Muted Structural Border (`#D1D5DB`):** Used solely for inputs, selected states, and active divider rules.

### Typography & Content Tone
- **Primary Ink (`#111827`):** Near-black charcoal ensuring optimal contrast ratios without harsh raster edges.
- **Secondary Slate (`#4B5563`):** Subdued descriptive labels, section headers, and metadata.
- **Tertiary Slate (`#6B7280`):** Minor captions, timestamps, and column headers.

### Academic Identity & Interactive Accents
- **Academic Deep Navy (`#0F2A4A`):** The primary anchor. Applied to top-level navigation, structural identity, primary commands, and confirmed states.
- **Active Cobalt Accent (`#1D4ED8`):** Focused selection states, active tab indicators, and interactive links.

### Evaluative & Status Semantics
Semantics are restrained and sober:
- **Verified / Awarded Marks (`#059669`):** Controlled emerald; conveys clearance, passing criteria, and validated score entry.
- **Review / Moderation Required (`#D97706`):** Deep amber; indicates partial scoring, pending reconciliation, or flagged annotations.
- **Critical Flag / Discrepancy (`#DC2626`):** Crisp brick red; flags malpractice warnings, total tally mismatches, and illegible page sections.

## Typography
The system employs an authoritative tripartite typographic pairing:
1. **Geist Sans** governs structural sectioning, panel headers, and view titles with architectural geometry and crisp terminal cuts.
2. **Inter** acts as the primary vehicle for high-legibility interface copy, micro-labels, inline notes, and rubric prose.
3. **JetBrains Mono** is mandatory for all numerical evaluation data: student candidate IDs, rubric maximums, input mark tallies, total percentages, and timestamp audit trails. It prevents visual jitter when scanning columns of marks.

### Application Guidelines
- Always render marks and arithmetic totals in tabular monospaced figures (`tabular-marks`).
- Use uppercase for meta-labels (`label-sm`) with subtle letter-spacing for document status tags and table headers.
- Never use decorative weights (e.g., Ultra Light or Black). Restrict the system to Regular (400), Medium (500), and Semi-Bold (600).

## Layout & Spacing
The layout follows an asymmetric dual-pane and multi-column architecture tailored for desktop evaluation setups (1280px and wider).

### Evaluation Workbench Grid
- **Global Canvas:** Split into a fixed-width left navigation/index rail (64px collapsed or 240px expanded), an expandable central evaluation document viewer (fluid, accounting for 60–70% of viewport width), and a fixed-width right scoring/rubric inspector (360px–420px).
- **Rhythm & Padding:** Built on a tight 4px baseline module. Operational evaluation screens leverage compact component gaps (`space-xs` to `space-md`), minimizing vertical mouse travel between questions.
- **Breakpoints:**
  - **Desktop (>= 1280px):** Default standard multi-pane evaluator layout. Document canvas and mark sheet side-by-side.
  - **Tablet (768px – 1279px):** Document canvas prioritised; rubric dock shifts to a bottom overlay sheet or tabbed drawer.
  - **Mobile (< 768px):** Restricted to administrative batch inspection, verification queues, and audit log reviews; grading workspace prompts for desktop workstation view.

## Elevation & Depth
Elevation in this system is planar, low-contrast, and strictly structural. Diffused, floating drop shadows and blur filters are excluded to avoid screen weight and maintain printing fidelity.

### Architectural Rules
- **Layer 0 (Canvas Base):** Warm ground (`#F8F9FA`).
- **Layer 1 (Working Surface):** Pure white panels (`#FFFFFF`) delineated solely by 1px crisp borders (`#E5E7EB`). 
- **Layer 2 (Contextual Menus & Dropdowns):** Pure white (`#FFFFFF`) framed with a sharpened outline (`#D1D5DB`) paired with a micro-offset shadow: `0 2px 4px rgba(17, 24, 39, 0.05)`.
- **Layer 3 (Modals & Severe Alerts):** Pure white container overlaid on a crisp semi-opaque backing (`rgba(15, 42, 74, 0.4)`). Container utilizes a structured keyline shadow: `0 4px 12px rgba(17, 24, 39, 0.08)`.

## Shapes
Shapes are grounded, rectangular, and restrained. There are no pill-shaped tags or bulbous buttons.

- **Standard Radius (0.25rem / 4px):** Applied to inputs, buttons, score adjustment steppers, badge pills, and selection rows.
- **Surface Panels (0.375rem / 6px):** Applied to dialog boxes, paper scan viewport containers, and floating annotation tooltips.
- **Zero Radius (0px):** Data table cells, column dividers, and the main inspection viewport frame remain purely rectilinear to maximize space and preserve alignment against scan edges.

## Components

### Buttons
- **Primary:** Background `#0F2A4A`, text `#FFFFFF`, 4px border radius. Hover state transitions to `#1E3A8A`. No drop shadows.
- **Secondary / Ghost:** Background transparent, 1px border `#E5E7EB`, text `#111827`. Hover state transitions to background `#F3F4F6`.
- **Destructive:** Background `#DC2626`, text `#FFFFFF`. Hover state `#B91C1C`.
- **Size Profiles:** Dense vertical padding (`0.375rem` vertical, `0.75rem` horizontal) with `13px` font sizing for workspace tools; standard `0.5rem` vertical for global actions.

### Marks Input & Number Stepper
- Monospaced numerical inputs (`tabular-marks`) enclosed in a 1px `#D1D5DB` container with right-aligned text. 
- Active focus state employs a clean 1px `#1D4ED8` ring without soft outer glow.
- Includes quick-increment mini step toggles integrated flush against the right inner border.

### Data Tables (Answer Sheet & Batch Rosters)
- Clean, high-density row heights (32px to 38px).
- Bottom hairline borders only (`#E5E7EB`); zebra stripes are omitted in favor of a subtle hover tint (`#F9FAFB`).
- Header cells styled with `label-sm`, uppercase, color `#6B7280`, with vertical borders omitted to maintain horizontal scanning speed.
- Monospace alignment: All candidate registration numbers, page sequences, and numerical marks are right-aligned with fixed character cells.

### Status Badges & Chips
- Subtle rectangular chips (4px radius) utilizing muted, accessible background tints with dark foreground text:
  - **Verified / Fully Scored:** Background `#ECFDF5`, text `#065F46`, border `#A7F3D0`.
  - **Flagged / Audit Needed:** Background `#FFFBEB`, text `#92400E`, border `#FDE68A`.
  - **Discrepancy / Error:** Background `#FEF2F2`, text `#991B1B`, border `#FECACA`.
  - **Unmarked / Draft:** Background `#F3F4F6`, text `#374151`, border `#E5E7EB`.

### Digital Manuscript Annotation Overlay
- Hairline pens and callout boxes placed directly on evaluated script viewports:
  - Green mark stamp (`#059669`) for positive allocation checkmarks.
  - Brick red cross/underline (`#DC2626`) for incorrect steps.
  - Academic navy callout flags (`#0F2A4A`) for pinned examiner commentary.

### Form Inputs & Checkboxes
- **Inputs:** Crisp 1px `#D1D5DB` outline, square appearance with 4px corners, `#111827` active text, `#9CA3AF` placeholder.
- **Checkboxes & Radios:** Sharp 4px rounded-corner square checkboxes and circular radios with a clean `#0F2A4A` fill upon active selection.