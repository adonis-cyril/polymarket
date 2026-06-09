"""Theme definitions — Polyadonis (default), Bloomberg, midnight, light."""

from __future__ import annotations

from terminal.themes.polyadonis import POLYADONIS_PALETTE

THEMES: dict[str, dict[str, str]] = {
    "polyadonis": POLYADONIS_PALETTE,
    "bloomberg": {
        "background": "#0a0e14",
        "surface": "#111820",
        "primary": "#ff8c00",
        "secondary": "#00d4aa",
        "accent": "#4da6ff",
        "error": "#ff4444",
        "warning": "#ffcc00",
        "text": "#e8e8e8",
        "muted": "#6b7c93",
        "border": "#2a3544",
        "success": "#00c853",
    },
    "midnight": {
        "background": "#0d1117",
        "surface": "#161b22",
        "primary": "#58a6ff",
        "secondary": "#3fb950",
        "accent": "#d2a8ff",
        "error": "#f85149",
        "warning": "#d29922",
        "text": "#c9d1d9",
        "muted": "#8b949e",
        "border": "#30363d",
        "success": "#3fb950",
    },
    "light": {
        "background": "#f5f5f5",
        "surface": "#ffffff",
        "primary": "#0066cc",
        "secondary": "#00875a",
        "accent": "#6b4c9a",
        "error": "#d32f2f",
        "warning": "#f57c00",
        "text": "#1a1a1a",
        "muted": "#666666",
        "border": "#cccccc",
        "success": "#2e7d32",
    },
}


def get_theme_css(theme_name: str) -> str:
    t = THEMES.get(theme_name, THEMES["polyadonis"])
    return f"""
$background: {t['background']};
$surface: {t['surface']};
$primary: {t['primary']};
$secondary: {t['secondary']};
$accent: {t['accent']};
$error: {t['error']};
$warning: {t['warning']};
$success: {t['success']};
$text: {t['text']};
$text-muted: {t['muted']};
$border: {t['border']};

Screen {{
    background: {t['background']};
}}

#workstation {{
    background: {t['background']};
}}

.header-bar {{
    background: {t['surface']};
    color: {t['primary']};
    text-style: bold;
    height: 1;
    padding: 0 1;
}}

.status-bar {{
    dock: bottom;
    height: 1;
    background: {t['surface']};
    color: {t['muted']};
    padding: 0 1;
}}

.pane-title {{
    background: {t['surface']};
    color: {t['primary']};
    text-style: bold;
    padding: 0 1;
    height: 1;
}}

.pane {{
    border: solid {t['border']};
    background: {t['background']};
}}

.metric-positive {{
    color: {t['success']};
}}

.metric-negative {{
    color: {t['error']};
}}

.metric-neutral {{
    color: {t['text']};
}}

.log-info {{
    color: {t['text']};
}}

.log-warning {{
    color: {t['warning']};
}}

.log-error {{
    color: {t['error']};
}}

.log-debug {{
    color: {t['muted']};
}}

.command-input {{
    dock: bottom;
    height: 3;
    border-top: solid {t['border']};
    background: {t['surface']};
}}

.command-input > Input {{
    background: {t['surface']};
    color: {t['text']};
    border: none;
}}

DataTable {{
    background: {t['background']};
    color: {t['text']};
}}

DataTable > .datatable--header {{
    background: {t['surface']};
    color: {t['primary']};
    text-style: bold;
}}

DataTable > .datatable--cursor {{
    background: {t['primary']} 30%;
}}

#chart-pane RichLog {{
    background: {t['background']};
}}

.notification {{
    background: {t['surface']};
    border: solid {t['primary']};
    color: {t['text']};
    padding: 1 2;
}}

LoadingIndicator {{
    color: {t['primary']};
}}

Footer {{
    background: {t['surface']};
    color: {t['muted']};
}}

TopBar {{
    background: {t['surface']};
    color: {t['text']};
    border-bottom: solid {t['border']};
}}

TopBar .status-ok {{
    color: {t['success']};
}}

TopBar .status-warn {{
    color: {t['warning']};
}}

MetricsBar {{
    background: {t['surface']};
    color: {t['muted']};
    border-top: solid {t['border']};
}}

ActivityPane, LeftPane {{
    background: {t['background']};
    border: solid {t['border']};
}}

ActivityPane .activity-header {{
    background: {t['surface']};
    color: {t['primary']};
}}

CommandBar {{
    background: {t['background']};
    border-top: solid {t['border']};
}}

CommandBar .prompt-label {{
    color: {t['primary']};
    text-style: bold;
}}

CommandOutput {{
    background: {t['surface']};
    border-top: solid {t['border']};
}}

#cmd-hint {{
    background: {t['surface']};
    color: {t['muted']};
}}
"""
