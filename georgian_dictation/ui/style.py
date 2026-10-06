APP_STYLE = r"""
* {
    font-size: 10pt;
    color: #E9EDF2;
}
QMainWindow, QWidget#Root { background: #101217; }
QWidget#Sidebar { background: #15181E; border-right: 1px solid #252A33; }
QLabel#Brand { font-size: 16pt; font-weight: 700; color: #F5F7FA; }
QLabel#BrandSub { color: #7F8A99; font-size: 9pt; }
QListWidget#Navigation { background: transparent; border: 0; outline: 0; }
QListWidget#Navigation::item { color: #AAB3BF; padding: 11px 14px; margin: 2px 8px; border-radius: 8px; }
QListWidget#Navigation::item:hover { background: #20242C; color: #FFFFFF; }
QListWidget#Navigation::item:selected { background: #263A3A; color: #66DBC4; }
QLabel#PageTitle { font-size: 21pt; font-weight: 700; color: #F7F9FB; }
QLabel#PageSubtitle { color: #8993A1; }
QFrame#Card { background: #191D24; border: 1px solid #292F39; border-radius: 12px; }
QLabel#CardTitle { font-size: 11pt; font-weight: 650; color: #F2F5F8; }
QLabel#Muted { color: #87919E; }
QLabel#StatusValue { font-size: 18pt; font-weight: 700; }
QPushButton { background: #252B34; border: 1px solid #343C48; border-radius: 8px; padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #2D3540; border-color: #465160; }
QPushButton:pressed { background: #20262E; }
QPushButton:disabled { color: #5E6672; background: #1B1F25; border-color: #282D35; }
QPushButton#Primary { background: #4FCBB3; color: #0A201B; border-color: #4FCBB3; padding: 10px 18px; }
QPushButton#Primary:hover { background: #65D8C2; }
QPushButton#Danger { color: #FF929C; }
QComboBox, QLineEdit, QPlainTextEdit, QKeySequenceEdit, QSpinBox, QDoubleSpinBox {
    background: #12151A; border: 1px solid #333A45; border-radius: 7px; padding: 7px 9px; selection-background-color: #3F8F82;
}
QComboBox:hover, QLineEdit:hover, QKeySequenceEdit:hover { border-color: #566170; }
QComboBox::drop-down { border: 0; width: 28px; }
QComboBox QAbstractItemView { background: #1B1F26; border: 1px solid #343B46; selection-background-color: #31544F; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #46505D; border-radius: 5px; background: #12151A; }
QCheckBox::indicator:checked { background: #50CFB6; border-color: #50CFB6; }
QRadioButton { spacing: 8px; }
QProgressBar { background: #111419; border: 1px solid #303640; border-radius: 6px; height: 11px; text-align: center; color: transparent; }
QProgressBar::chunk { background: #55D6BE; border-radius: 5px; }
QTableWidget { background: #15191F; alternate-background-color: #181D24; border: 1px solid #2B313B; border-radius: 9px; gridline-color: #272D36; selection-background-color: #294540; }
QHeaderView::section { background: #1D222A; color: #9EA8B5; padding: 8px; border: 0; border-bottom: 1px solid #303641; font-weight: 600; }
QTabWidget::pane { border: 0; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar::handle:vertical { min-height: 30px; background: #353C47; border-radius: 5px; }
QToolTip { background: #252B34; color: white; border: 1px solid #434C59; padding: 5px; }
"""
