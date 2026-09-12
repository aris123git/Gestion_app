"""Internationalisation NexaGes : Français, English, 中文.

Usage ::

    from app.i18n import t, get_language, set_language

    label = t("nav.pos")
"""

from __future__ import annotations

from typing import Dict

from app.services import settings_service

SETTING_LANGUAGE = "ui_language"

LANG_FR = "fr"
LANG_EN = "en"
LANG_ZH = "zh"

LANGUAGE_LABELS = {
    LANG_FR: "Français",
    LANG_EN: "English",
    LANG_ZH: "中文",
}

# Clé → {lang: texte}. Langue absente → français → clé.
_STRINGS: Dict[str, Dict[str, str]] = {
    # --- Navigation --------------------------------------------------------
    "nav.pos": {"fr": "Caisse", "en": "POS", "zh": "收银"},
    "nav.tables": {"fr": "Tables", "en": "Tables", "zh": "桌台"},
    "nav.orders": {"fr": "Commandes", "en": "Orders", "zh": "订单"},
    "nav.dashboard": {"fr": "Tableau de bord", "en": "Dashboard", "zh": "仪表盘"},
    "nav.products": {"fr": "Produits", "en": "Products", "zh": "商品"},
    "nav.categories": {"fr": "Catégories", "en": "Categories", "zh": "分类"},
    "nav.stock": {"fr": "Stock", "en": "Stock", "zh": "库存"},
    "nav.purchases": {"fr": "Achats", "en": "Purchases", "zh": "采购"},
    "nav.clients": {"fr": "Clients", "en": "Customers", "zh": "客户"},
    "nav.debts": {"fr": "Dettes", "en": "Debts", "zh": "欠款"},
    "nav.credits": {"fr": "Avoirs", "en": "Store credit", "zh": "储值"},
    "nav.suppliers": {"fr": "Fournisseurs", "en": "Suppliers", "zh": "供应商"},
    "nav.expenses": {"fr": "Dépenses", "en": "Expenses", "zh": "支出"},
    "nav.reports": {"fr": "Rapports", "en": "Reports", "zh": "报表"},
    "nav.audit": {"fr": "Journal d'audit", "en": "Audit log", "zh": "审计日志"},
    "nav.assistant": {"fr": "Assistant", "en": "Assistant", "zh": "助手"},
    "nav.users": {"fr": "Utilisateurs", "en": "Users", "zh": "用户"},
    "nav.settings": {"fr": "Paramètres", "en": "Settings", "zh": "设置"},
    # --- Commun ------------------------------------------------------------
    "common.save": {"fr": "Enregistrer", "en": "Save", "zh": "保存"},
    "common.cancel": {"fr": "Annuler", "en": "Cancel", "zh": "取消"},
    "common.delete": {"fr": "Supprimer", "en": "Delete", "zh": "删除"},
    "common.edit": {"fr": "Modifier", "en": "Edit", "zh": "编辑"},
    "common.add": {"fr": "Ajouter", "en": "Add", "zh": "添加"},
    "common.search": {"fr": "Rechercher…", "en": "Search…", "zh": "搜索…"},
    "common.all": {"fr": "Tous", "en": "All", "zh": "全部"},
    "common.yes": {"fr": "Oui", "en": "Yes", "zh": "是"},
    "common.no": {"fr": "Non", "en": "No", "zh": "否"},
    "common.close": {"fr": "Fermer", "en": "Close", "zh": "关闭"},
    "common.language": {"fr": "Langue", "en": "Language", "zh": "语言"},
    "common.restart_required": {
        "fr": "L'application va se fermer. Relancez-la pour appliquer le changement.",
        "en": "The application will close. Relaunch it to apply the change.",
        "zh": "应用即将关闭。请重新启动以应用更改。",
    },
    # --- Login -------------------------------------------------------------
    "login.title": {"fr": "Connexion", "en": "Sign in", "zh": "登录"},
    "login.username": {"fr": "Identifiant", "en": "Username", "zh": "用户名"},
    "login.password": {"fr": "Mot de passe", "en": "Password", "zh": "密码"},
    "login.submit": {"fr": "Se connecter", "en": "Sign in", "zh": "登录"},
    # --- Caisse ------------------------------------------------------------
    "pos.title": {"fr": "Caisse", "en": "POS", "zh": "收银"},
    "pos.cart": {"fr": "Panier", "en": "Cart", "zh": "购物车"},
    "pos.barcode": {
        "fr": "Scanner / saisir un code-barres puis Entrée",
        "en": "Scan / enter a barcode then Enter",
        "zh": "扫描或输入条码后按回车",
    },
    "pos.search_product": {
        "fr": "Rechercher un produit…",
        "en": "Search a product…",
        "zh": "搜索商品…",
    },
    "pos.all_categories": {
        "fr": "Toutes les catégories",
        "en": "All categories",
        "zh": "全部分类",
    },
    "pos.product": {"fr": "Produit", "en": "Product", "zh": "商品"},
    "pos.price": {"fr": "Prix", "en": "Price", "zh": "价格"},
    "pos.stock": {"fr": "Stock", "en": "Stock", "zh": "库存"},
    "pos.add_to_cart": {
        "fr": "Ajouter au panier",
        "en": "Add to cart",
        "zh": "加入购物车",
    },
    "pos.clear_cart": {"fr": "Vider", "en": "Clear", "zh": "清空"},
    "pos.client": {"fr": "Client :", "en": "Customer:", "zh": "客户："},
    "pos.discount": {"fr": "Remise :", "en": "Discount:", "zh": "折扣："},
    "pos.total": {"fr": "Total : {amount}", "en": "Total: {amount}", "zh": "合计：{amount}"},
    "pos.checkout": {
        "fr": "Encaisser (Payer)",
        "en": "Checkout (Pay)",
        "zh": "收款（支付）",
    },
    "pos.hold": {"fr": "Mettre en attente", "en": "Hold", "zh": "挂单"},
    "pos.resume": {"fr": "Reprendre…", "en": "Resume…", "zh": "取单…"},
    "pos.browse_categories": {
        "fr": "Choisissez une catégorie",
        "en": "Choose a category",
        "zh": "选择分类",
    },
    "pos.back_categories": {
        "fr": "← Catégories",
        "en": "← Categories",
        "zh": "← 分类",
    },
    # --- Produits / catégories --------------------------------------------
    "products.title": {"fr": "Produits", "en": "Products", "zh": "商品"},
    "categories.title": {
        "fr": "Catégories & Unités",
        "en": "Categories & Units",
        "zh": "分类与单位",
    },
    "categories.section": {"fr": "Catégories", "en": "Categories", "zh": "分类"},
    "categories.units": {"fr": "Unités", "en": "Units", "zh": "单位"},
    "categories.name": {"fr": "Nom", "en": "Name", "zh": "名称"},
    "categories.description": {
        "fr": "Description",
        "en": "Description",
        "zh": "说明",
    },
    "categories.new": {
        "fr": "Nouvelle catégorie",
        "en": "New category",
        "zh": "新建分类",
    },
    "categories.edit": {
        "fr": "Modifier la catégorie",
        "en": "Edit category",
        "zh": "编辑分类",
    },
    "product.image": {"fr": "Image", "en": "Image", "zh": "图片"},
    "product.choose_image": {
        "fr": "Choisir une image…",
        "en": "Choose an image…",
        "zh": "选择图片…",
    },
    "product.clear_image": {
        "fr": "Retirer l'image",
        "en": "Remove image",
        "zh": "移除图片",
    },
    "product.no_image": {
        "fr": "Aucune image",
        "en": "No image",
        "zh": "无图片",
    },
    # --- Paramètres --------------------------------------------------------
    "settings.title": {"fr": "Paramètres", "en": "Settings", "zh": "设置"},
    "settings.tab.shop": {"fr": "Commerce", "en": "Business", "zh": "店铺"},
    "settings.tab.appearance": {
        "fr": "Apparence du ticket",
        "en": "Ticket appearance",
        "zh": "小票外观",
    },
    "settings.language_hint": {
        "fr": "Change la langue de l'interface (Français, English, 中文).",
        "en": "Changes the interface language (French, English, Chinese).",
        "zh": "更改界面语言（法语、英语、中文）。",
    },
    "settings.catalog_section": {
        "fr": "Catalogue (caisse)",
        "en": "Catalog (POS)",
        "zh": "目录（收银）",
    },
    "settings.catalog_images": {
        "fr": "Afficher les produits avec images en caisse",
        "en": "Show product images at the POS",
        "zh": "在收银界面显示商品图片",
    },
    "settings.catalog_images_tip": {
        "fr": "Grille visuelle : idéal mercerie, boutique, cosmétique… "
        "Ajoutez une image sur chaque fiche produit.",
        "en": "Visual grid: ideal for haberdashery, retail, cosmetics… "
        "Add an image on each product form.",
        "zh": "可视化网格：适合服饰辅料店、零售、化妆品等。请在商品资料中添加图片。",
    },
    "settings.catalog_categories": {
        "fr": "Navigation par catégories (sélection visuelle)",
        "en": "Browse by categories (visual selection)",
        "zh": "按分类浏览（可视化选择）",
    },
    "settings.catalog_categories_tip": {
        "fr": "En caisse : d'abord les catégories (ex. fils, boutons, tissus), "
        "puis les produits de la catégorie choisie — plus fluide pour une mercerie.",
        "en": "At POS: first pick a category (e.g. threads, buttons, fabrics), "
        "then the products — smoother for a haberdashery.",
        "zh": "收银时先选分类（如线材、纽扣、布料），再选商品——更适合辅料店。",
    },
    "settings.language_saved": {
        "fr": "Langue enregistrée.\n\n{restart}",
        "en": "Language saved.\n\n{restart}",
        "zh": "语言已保存。\n\n{restart}",
    },
}


_current: str | None = None


def normalize_language(code: str | None) -> str:
    raw = (code or "").strip().lower().replace("-", "_")
    if raw.startswith("zh") or raw in ("cn", "chinese", "中文"):
        return LANG_ZH
    if raw.startswith("en") or raw in ("english", "anglais"):
        return LANG_EN
    return LANG_FR


def get_language() -> str:
    global _current
    if _current is None:
        _current = normalize_language(
            settings_service.get_setting(SETTING_LANGUAGE, LANG_FR)
        )
    return _current


def set_language(code: str) -> str:
    """Persiste et active la langue. Retourne le code normalisé."""
    global _current
    lang = normalize_language(code)
    settings_service.set_setting(SETTING_LANGUAGE, lang)
    _current = lang
    return lang


def language_label(code: str | None = None) -> str:
    return LANGUAGE_LABELS.get(normalize_language(code or get_language()), "Français")


def t(key: str, default: str | None = None, **kwargs) -> str:
    """Traduit une clé. Fallback : français → default → clé."""
    lang = get_language()
    entry = _STRINGS.get(key) or {}
    text = entry.get(lang) or entry.get(LANG_FR) or default or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
