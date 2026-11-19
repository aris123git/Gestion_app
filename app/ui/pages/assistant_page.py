"""Assistant de gestion — recommandations par règles métier, groupées par urgence."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from app.services.assistant_service import AssistantService
from app.ui.state import AppState
from app.ui.widgets.helpers import make_card, page_title

LEVEL_STYLE = {
    'danger': ('#fee2e2', '#991b1b', '🔴'),
    'warning': ('#fef3c7', '#92400e', '🟠'),
    'info': ('#dbeafe', '#1e40af', '🔵'),
}
LEVEL_ORDER = ['danger', 'warning', 'info']
LEVEL_TITLE = {'danger': 'À traiter maintenant', 'warning': 'À surveiller', 'info': 'Pour information'}

# categorie de la recommandation -> (libellé du nav, méthode optionnelle à appeler sur la page ouverte)
CATEGORY_TARGET = {
    'stock': ('nav.stock', 'À commander'),
    'dette': ('nav.clients', 'unpaid'),
    'fournisseur': ('nav.stock', 'Achats'),
    'produit': ('nav.products', None),
    'client': ('nav.clients', None),
    'ventes': ('nav.reports', None),
}


class AssistantPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Assistant de gestion')))
        header.addStretch()
        refresh = QPushButton(t('Actualiser'))
        refresh.setObjectName('Primary')
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        self._layout.addLayout(header)
        self.sections: dict[str, QVBoxLayout] = {}
        self.section_cards: dict[str, QWidget] = {}
        for level in LEVEL_ORDER:
            title = QLabel(f"<b>{LEVEL_STYLE[level][2]} {t(LEVEL_TITLE[level])}</b>")
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(8)
            card = make_card(box)
            self._layout.addWidget(title)
            self._layout.addWidget(card)
            self.sections[level] = inner
            self.section_cards[level] = card
        self.empty_label = QLabel(t('Rien à signaler pour le moment : tout est sous contrôle.'))
        self.empty_label.setStyleSheet('color: #64748b;')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.empty_label)
        self._layout.addStretch(1)

    def refresh(self) -> None:
        rows = AssistantService.recommendations()
        for level in LEVEL_ORDER:
            inner = self.sections[level]
            while inner.count():
                item = inner.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            items = [r for r in rows if r.level == level]
            self.section_cards[level].setVisible(bool(items))
            for rec in items:
                inner.addWidget(self._row(rec))
        self.empty_label.setVisible(not rows)

    def _row(self, rec) -> QWidget:
        bg, fg, _icon = LEVEL_STYLE.get(rec.level, LEVEL_STYLE['info'])
        row = QWidget()
        row.setStyleSheet(f'background: {bg}; border-radius: 8px;')
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        text = QLabel(f"<b style='color:{fg}'>{rec.title}</b><br><span style='color:{fg}'>{rec.detail}</span>")
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(text, 1)
        target = CATEGORY_TARGET.get(rec.category)
        if target:
            go = QPushButton(t('Voir'))
            go.clicked.connect(lambda _=False, tgt=target: self._go_to(*tgt))
            h.addWidget(go, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _go_to(self, nav_label: str, tab_label: str | None) -> None:
        window = self.window()
        if window is None or not hasattr(window, '_select_page_by_label'):
            return
        page = window._select_page_by_label(t(nav_label))
        if page is None:
            return
        if tab_label == 'unpaid' and hasattr(page, 'show_unpaid'):
            page.show_unpaid()
        elif tab_label and hasattr(page, 'select_tab'):
            page.select_tab(tab_label)
