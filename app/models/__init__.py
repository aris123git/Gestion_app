"""Modèles ORM SQLAlchemy de l'application."""

from app.models.audit import AuditLog
from app.models.avoir import Avoir, AvoirRedemption
from app.models.cash_session import CashSession
from app.models.category import Category
from app.models.client import Client
from app.models.debt import Debt, DebtPayment
from app.models.dining_table import DiningTable
from app.models.expense import Expense
from app.models.loyalty import CustomerPoints, CustomerPointsHistory
from app.models.open_order import OpenOrder, OpenOrderItem
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseItem
from app.models.sale import Payment, Sale, SaleItem
from app.models.settings import Setting, ShopInfo
from app.models.stock import StockMovement
from app.models.supplier import Supplier
from app.models.supplier_debt import SupplierDebt, SupplierDebtPayment
from app.models.unit import Unit
from app.models.user import User

__all__ = [
    "AuditLog",
    "Avoir",
    "AvoirRedemption",
    "CashSession",
    "Category",
    "Client",
    "CustomerPoints",
    "CustomerPointsHistory",
    "Debt",
    "DebtPayment",
    "DiningTable",
    "Expense",
    "OpenOrder",
    "OpenOrderItem",
    "Payment",
    "PriceHistory",
    "Product",
    "Purchase",
    "PurchaseItem",
    "Sale",
    "SaleItem",
    "Setting",
    "ShopInfo",
    "StockMovement",
    "Supplier",
    "SupplierDebt",
    "SupplierDebtPayment",
    "Unit",
    "User",
]
