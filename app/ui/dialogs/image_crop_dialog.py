"""Recadrage d'une image (photo d'un en-tête) : on tire un rectangle, seule cette partie est conservée."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QRubberBand, QVBoxLayout

from app import config
from app.i18n import t
from app.ui.widgets.dialog_fit import fit_dialog_to_screen

MAX_WIDTH = 1800          # largeur maximale de l'image conservée (assez pour l'impression, fichier léger)


def load_image(path: str | Path) -> Image.Image:
    """Ouvre l'image en tenant compte de l'orientation de la photo (téléphone)."""
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def crop_and_save(image: Image.Image, box: tuple[int, int, int, int] | None, name: str = "proforma_banner") -> Path:
    """Recadre (box = gauche, haut, droite, bas en pixels, ou None pour tout garder) et enregistre dans le dossier du logiciel."""
    if box is not None:
        left, top, right, bottom = box
        if right - left < 20 or bottom - top < 20:
            raise ValueError("La zone choisie est trop petite.")
        image = image.crop(box)
    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)), Image.LANCZOS)
    config.ensure_directories()
    folder = Path(config.DATA_DIR) / "branding"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}.png"
    image.save(out, "PNG")
    return out


class _Canvas(QLabel):
    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin = QPoint()
        self.selection: QRect | None = None

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._origin = e.position().toPoint()
        self._band.setGeometry(QRect(self._origin, QSize()))
        self._band.show()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self._band.setGeometry(QRect(self._origin, e.position().toPoint()).normalized().intersected(self.rect()))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        rect = self._band.geometry()
        self.selection = rect if rect.width() > 5 and rect.height() > 5 else None


class ImageCropDialog(QDialog):
    def __init__(self, path: str | Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Recadrer l'image"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=520, min_height=420, preferred_width=900, preferred_height=720)
        self.image = load_image(path)
        self.result_path: Path | None = None
        w, h = self.image.size
        scale = min(820 / w, 560 / h, 1.0)
        self.scale = scale
        data = self.image.tobytes("raw", "RGB")
        qimg = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg).scaled(round(w * scale), round(h * scale), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(t("Tirez un rectangle autour de l'en-tête (logo, nom, coordonnées). Seule cette partie sera imprimée.")))
        self.canvas = _Canvas(pix)
        root.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignCenter)
        bb = QDialogButtonBox()
        crop = bb.addButton(t("Recadrer et utiliser"), QDialogButtonBox.ButtonRole.AcceptRole)
        whole = bb.addButton(t("Garder l'image entière"), QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        crop.clicked.connect(self._use_selection)
        whole.clicked.connect(self._use_whole)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.status = QLabel()
        root.addWidget(self.status)

    def selection_box(self) -> tuple[int, int, int, int] | None:
        r = self.canvas.selection
        if r is None:
            return None
        s = self.scale
        return (round(r.left() / s), round(r.top() / s), round((r.right() + 1) / s), round((r.bottom() + 1) / s))

    def _finish(self, box) -> None:
        try:
            self.result_path = crop_and_save(self.image, box)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.accept()

    def _use_selection(self) -> None:
        box = self.selection_box()
        if box is None:
            self.status.setText(t("Tirez d'abord un rectangle sur l'image."))
            return
        self._finish(box)

    def _use_whole(self) -> None:
        self._finish(None)
