"""Dark, minimalist theme for the WinWhispr native desktop app (Qt Style Sheets)."""

from __future__ import annotations

COLORS = {
    "bg": "#0a0c12",
    "surface": "#111420",
    "surface2": "#161a28",
    "surface3": "#1c2132",
    "border": "#232a3d",
    "border_soft": "#1a1f2e",
    "text": "#eef1f8",
    "text_dim": "#b6bdd0",
    "muted": "#7a8199",
    "accent": "#7c5cff",
    "accent2": "#22d3ee",
    "success": "#34d399",
    "danger": "#f87171",
    "amber": "#fbbf24",
}


def stylesheet() -> str:
    c = COLORS
    return f"""
    * {{
        font-family: 'Segoe UI', 'Inter', sans-serif;
        color: {c['text']};
        outline: none;
    }}
    QWidget#Root {{
        background: {c['bg']};
    }}

    /* ---- sidebar ---- */
    QFrame#Sidebar {{
        background: {c['surface']};
        border-right: 1px solid {c['border_soft']};
    }}
    QLabel#BrandName {{
        font-size: 17px;
        font-weight: 700;
        padding: 2px 0;
    }}
    QLabel#BrandSub {{
        font-size: 11px;
        color: {c['muted']};
        padding: 1px 0;
    }}
    QLabel#BrandMark {{
        background: {c['accent']};
        border-radius: 9px;
        font-size: 18px;
        font-weight: 800;
        color: {c['bg']};
    }}
    QLabel#NavLabel {{
        font-size: 10px;
        color: {c['muted']};
        letter-spacing: 1px;
        padding: 4px 0;
    }}

    /* section header toggle */
    QToolButton#SectionHeader {{
        background: transparent;
        border: none;
        text-align: left;
        padding: 10px 12px;
        border-radius: 10px;
        font-size: 13px;
        font-weight: 600;
        color: {c['text_dim']};
    }}
    QToolButton#SectionHeader:hover {{
        background: {c['surface2']};
        color: {c['text']};
    }}
    QToolButton#SectionHeader:checked {{
        color: {c['text']};
    }}
    QFrame#SectionBody {{
        background: transparent;
    }}

    QLabel.FieldLabel {{
        font-size: 12px;
        color: {c['muted']};
        padding: 2px 0;
    }}
    QLabel.FieldValue {{
        font-size: 12px;
        font-weight: 700;
        color: {c['text']};
        padding: 2px 0;
    }}
    QLabel.Hint {{
        font-size: 11px;
        color: {c['muted']};
        padding: 1px 0;
    }}

    /* ---- header ---- */
    QLabel#Avatar {{
        background: {c['accent']};
        border-radius: 14px;
        font-size: 19px;
        font-weight: 700;
        color: {c['bg']};
    }}
    QLabel#Greeting {{
        font-size: 23px;
        font-weight: 700;
        padding: 4px 0;
    }}
    QLabel#DateLine {{
        font-size: 13px;
        color: {c['muted']};
        padding: 2px 0;
    }}
    QFrame#StatusChip {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 15px;
    }}
    QLabel#StatusText {{
        font-size: 12px;
        color: {c['text_dim']};
        padding: 2px 0;
    }}
    QFrame#HotkeyHint {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#HintText {{
        font-size: 12px;
        color: {c['text_dim']};
        padding: 2px 0;
    }}
    QLabel.Kbd {{
        background: {c['surface3']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 2px 7px;
        font-size: 11px;
        font-weight: 700;
        color: {c['text_dim']};
    }}

    /* ---- section titles ---- */
    QLabel.SectionTitle {{
        font-size: 12px;
        color: {c['muted']};
        letter-spacing: 1px;
        font-weight: 600;
        padding: 3px 0;
    }}
    QLabel#CountPill {{
        font-size: 11px;
        color: {c['muted']};
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 3px 10px;
    }}

    /* ---- metric cards ---- */
    QFrame.MetricCard {{
        background: {c['surface']};
        border: 1px solid {c['border_soft']};
        border-radius: 16px;
    }}
    QLabel.MetricIcon {{
        background: {c['surface3']};
        border-radius: 10px;
        font-size: 16px;
    }}
    QLabel.MetricValue {{
        font-size: 27px;
        font-weight: 800;
        padding: 4px 0;
    }}
    QLabel.MetricUnit {{
        font-size: 13px;
        font-weight: 600;
        color: {c['muted']};
        padding: 3px 0;
    }}
    QLabel.MetricLabel {{
        font-size: 12px;
        color: {c['muted']};
        padding: 2px 0;
    }}

    /* ---- note cards ---- */
    QFrame.NoteCard {{
        background: {c['surface']};
        border: 1px solid {c['border_soft']};
        border-radius: 14px;
    }}
    QFrame.NoteCardFresh {{
        background: {c['surface']};
        border: 1px solid {c['accent']};
        border-radius: 14px;
    }}
    QLabel.NoteText {{
        font-size: 14px;
        color: {c['text']};
        padding: 2px 0;
    }}
    QLabel.NoteMeta {{
        font-size: 11px;
        color: {c['muted']};
        padding: 1px 0;
    }}
    QLabel#EmptyTitle {{
        font-size: 15px;
        font-weight: 600;
        color: {c['text_dim']};
        padding: 3px 0;
    }}
    QLabel#EmptyBody {{
        font-size: 12px;
        color: {c['muted']};
        padding: 2px 0;
    }}
    QFrame#EmptyState {{
        border: 1px dashed {c['border']};
        border-radius: 16px;
    }}

    /* ---- inputs ---- */
    QComboBox, QLineEdit {{
        background: {c['surface3']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 7px 10px;
        font-size: 13px;
        color: {c['text']};
    }}
    QComboBox:hover, QLineEdit:focus {{
        border: 1px solid {c['accent']};
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        selection-background-color: {c['accent']};
        color: {c['text']};
        padding: 4px;
    }}

    QPushButton.Primary {{
        background: {c['accent']};
        border: none;
        border-radius: 10px;
        padding: 9px 14px;
        font-size: 13px;
        font-weight: 600;
        color: {c['bg']};
    }}
    QPushButton.Primary:hover {{ background: #8f73ff; }}
    QPushButton.Primary:disabled {{ background: {c['surface3']}; color: {c['muted']}; }}

    QPushButton.Ghost {{
        background: {c['surface3']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 12px;
        color: {c['text_dim']};
    }}
    QPushButton.Ghost:hover {{ border: 1px solid {c['accent']}; color: {c['text']}; }}

    QPushButton.DangerGhost {{
        background: {c['surface3']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 12px;
        color: {c['danger']};
    }}
    QPushButton.DangerGhost:hover {{ background: {c['danger']}; border: 1px solid {c['danger']}; color: #ffffff; }}

    QPushButton#IconBtn {{
        background: {c['surface3']};
        border: none;
        border-radius: 8px;
        font-size: 13px;
        color: {c['muted']};
    }}
    QPushButton#IconBtn:hover {{ background: {c['border']}; color: {c['text']}; }}
    QPushButton#CollapseBtn {{
        background: transparent;
        border: none;
        border-radius: 8px;
        color: {c['muted']};
        font-size: 16px;
    }}
    QPushButton#CollapseBtn:hover {{ background: {c['surface3']}; color: {c['text']}; }}

    QPushButton#QuitBtn {{
        background: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        color: {c['muted']};
        font-size: 16px;
    }}
    QPushButton#QuitBtn:hover {{ background: {c['danger']}; border: 1px solid {c['danger']}; color: #ffffff; }}

    /* ---- slider ---- */
    QSlider::groove:horizontal {{
        height: 5px;
        background: {c['surface3']};
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {c['accent']};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff;
        width: 15px;
        height: 15px;
        margin: -6px 0;
        border-radius: 8px;
    }}

    /* ---- checkbox ---- */
    QCheckBox {{ font-size: 12px; color: {c['text_dim']}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border-radius: 5px;
        border: 1px solid {c['border']};
        background: {c['surface3']};
    }}
    QCheckBox::indicator:checked {{
        background: {c['accent']};
        border: 1px solid {c['accent']};
    }}

    /* ---- speaker row ---- */
    QFrame.SpeakerRow {{
        background: {c['surface2']};
        border: 1px solid {c['border_soft']};
        border-radius: 9px;
    }}
    QLabel.SpeakerName {{ font-size: 12px; font-weight: 600; color: {c['text']}; padding: 1px 0; }}
    QLabel.SpeakerMeta {{ font-size: 11px; color: {c['muted']}; padding: 1px 0; }}

    /* ---- scroll areas ---- */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border']}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #2e3650; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QFrame#Divider {{ background: {c['border_soft']}; max-height: 1px; }}
    """
