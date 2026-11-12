import os, shutil, tempfile, unittest
from pathlib import Path

_D = tempfile.mkdtemp(prefix="gestion_crop_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image  # noqa: E402


class ImageCropTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_D, ignore_errors=True)

    def _photo(self):
        p = Path(_D) / "photo.jpg"
        im = Image.new("RGB", (3000, 2000), (200, 200, 200))
        for x in range(500, 2500):
            for y in range(300, 700):
                im.putpixel((x, y), (0, 0, 200))        # « en-tête » bleu au milieu du décor gris
        im.save(p)
        return p

    def test_crop_keeps_only_selection_and_downsizes(self):
        from app.ui.dialogs.image_crop_dialog import crop_and_save, load_image
        out = crop_and_save(load_image(self._photo()), (500, 300, 2500, 700))
        im = Image.open(out)
        self.assertEqual(im.width, 1800)                         # réduit à la largeur maximale
        self.assertAlmostEqual(im.height / im.width, 400 / 2000, places=2)
        px = im.getpixel((10, 10))                               # que du bleu (JPEG : approximatif) : plus de décor
        self.assertTrue(px[0] < 40 and px[1] < 40 and px[2] > 160, px)
        with self.assertRaises(ValueError):
            crop_and_save(load_image(self._photo()), (10, 10, 15, 15))

    def test_dialog_selection_maps_to_original_pixels(self):
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from app.ui.dialogs.image_crop_dialog import ImageCropDialog
        dlg = ImageCropDialog(self._photo())
        self.assertIsNone(dlg.selection_box())
        s = dlg.scale
        dlg.canvas.selection = QRect(round(500 * s), round(300 * s), round(2000 * s), round(400 * s))
        l, t_, r, b = dlg.selection_box()
        for got, want in ((l, 500), (t_, 300), (r, 2500), (b, 700)):
            self.assertLess(abs(got - want), 6)
        dlg._use_selection()
        self.assertTrue(dlg.result_path and dlg.result_path.exists())


if __name__ == "__main__":
    unittest.main()
