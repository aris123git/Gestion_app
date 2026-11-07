"""Messages groupés : numéros, segments, garde-fous anti-spam, e-mail séquentiel."""
import os, shutil, tempfile, unittest
from datetime import datetime, timedelta

_D = tempfile.mkdtemp(prefix="gestion_msg_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.sale import Sale  # noqa: E402
from app.services import messaging_service as ms, settings_service  # noqa: E402


class MessagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _client(self, name, phone="", email="", debt=0, no_marketing=False):
        with session_scope() as s:
            c = Client(name=name, phone=phone, email=email, debt=debt, no_marketing=no_marketing)
            s.add(c); s.flush()
            return c.id

    def _sale(self, client_id, when, n=[0]):
        n[0] += 1
        with session_scope() as s:
            s.add(Sale(ticket_number=f"T-MSG-{n[0]}", client_id=client_id, date=when, total=1000, status="completed"))

    def test_normalize_phone_and_link(self):
        self.assertEqual(ms.normalize_phone("70 12 34 56"), "22670123456")
        self.assertEqual(ms.normalize_phone("+226 70 12 34 56"), "22670123456")
        self.assertEqual(ms.normalize_phone("0022670123456"), "22670123456")
        self.assertEqual(ms.normalize_phone("22670123456"), "22670123456")
        self.assertEqual(ms.normalize_phone("+33 6 12 34 56 78"), "33612345678")
        self.assertIsNone(ms.normalize_phone("123"))
        self.assertIsNone(ms.normalize_phone(""))
        link = ms.whatsapp_link("70 12 34 56", "Bonjour Aïcha & co")
        self.assertTrue(link.startswith("https://wa.me/22670123456?text="))
        self.assertIn("Bonjour%20A", link)
        self.assertNotIn(" ", link)

    def test_segments_and_guards(self):
        settings_service.set_setting("messaging_min_gap_days", "3")
        now = datetime.now()
        a = self._client("Aicha Seg", "70 00 00 01", "a@x.com")
        b = self._client("Boukary Seg", "70 00 00 02", "b@x.com", debt=5000)
        c = self._client("Chantal Seg", "70 00 00 03", "c@x.com", no_marketing=True)
        d = self._client("Dramane Seg", "", "")                       # injoignable
        self._sale(a, now - timedelta(days=2))
        self._sale(b, now - timedelta(days=200))
        self._sale(c, now - timedelta(days=2))
        names = lambda rows: {r.name for r in rows}  # noqa: E731
        inrange = ms.find_recipients(ms.SEG_BOUGHT, ms.WHATSAPP, start=now - timedelta(days=5), end=now + timedelta(days=1))
        self.assertIn("Aicha Seg", names(inrange))
        self.assertNotIn("Boukary Seg", names(inrange))
        self.assertNotIn("Chantal Seg", names(inrange))           # ne plus contacter
        self.assertNotIn("Dramane Seg", names(ms.find_recipients(ms.SEG_ALL, ms.WHATSAPP)))
        self.assertNotIn("Dramane Seg", names(ms.find_recipients(ms.SEG_ALL, ms.EMAIL)))
        self.assertEqual(names(ms.find_recipients(ms.SEG_INACTIVE, ms.WHATSAPP, days=90)) & {"Aicha Seg", "Boukary Seg"}, {"Boukary Seg"})
        self.assertIn("Boukary Seg", names(ms.find_recipients(ms.SEG_DEBT, ms.EMAIL)))
        with self.assertRaises(ValueError):
            ms.find_recipients(ms.SEG_BOUGHT, ms.WHATSAPP, start=now, end=now - timedelta(days=1))
        # déjà contacté récemment : exclu ; désinscription : exclu
        ms.log(a, ms.WHATSAPP, ms.SENT, "test")
        self.assertNotIn("Aicha Seg", names(ms.find_recipients(ms.SEG_ALL, ms.WHATSAPP)))
        self.assertIn("Aicha Seg", names(ms.find_recipients(ms.SEG_ALL, ms.WHATSAPP, respect_gap=False)))
        ms.opt_out(b)
        self.assertNotIn("Boukary Seg", names(ms.find_recipients(ms.SEG_ALL, ms.EMAIL)))

    def test_render_placeholders_and_footer(self):
        r = ms.Recipient(1, "Aicha Ouedraogo", "70123456", "a@x.com", 12500)
        text = ms.render("Bonjour {prenom}, vous devez {dette} à {entreprise}. {inconnu}", r, "Ma Boutique")
        self.assertIn("Bonjour Aicha", text)
        self.assertIn("12 500 FCFA", text)
        self.assertIn("Ma Boutique", text)
        self.assertIn("{inconnu}", text)
        self.assertTrue(text.endswith("répondez STOP."))
        self.assertNotIn("STOP", ms.render("Salut", r, footer=False))

    def test_email_campaign_sequential_cap_and_failure(self):
        settings_service.set_setting("messaging_cap_email", "3")
        settings_service.set_setting("messaging_min_gap_days", "0")
        rows = [ms.Recipient(self._client(f"E{i}", email=f"e{i}@x.com"), f"E{i}", "", f"e{i}@x.com", 0) for i in range(5)]
        sent, pauses, seen = [], [], []

        def sender(to, subject, body):
            if to == "e1@x.com":
                raise RuntimeError("boîte pleine")
            sent.append((to, subject, body))

        self.assertEqual(ms.sent_today(ms.EMAIL), 0)
        res = ms.send_email_campaign(rows, "Promo", "Bonjour {prenom}", campaign="c1", sender=sender, delay=2, sleep=pauses.append,
                                     progress=lambda i, n, r, st: seen.append((i, st)))
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["sent"], 3)                              # les échecs ne comptent pas dans le plafond
        self.assertEqual([t for t, _s, _b in sent], ["e0@x.com", "e2@x.com", "e3@x.com"])
        self.assertTrue(res["capped"])                               # plafond de 3 envois/jour atteint
        self.assertTrue(all(p == 2 for p in pauses))
        self.assertTrue(all("STOP" in b for _t, _s, b in sent))
        self.assertEqual(ms.remaining_today(ms.EMAIL), 0)
        with self.assertRaises(ValueError):
            ms.send_email_campaign(rows, "", "x", campaign="c", sender=sender)
        with self.assertRaises(ValueError):
            ms.send_email_campaign(rows, "Objet", "x", campaign="c")   # SMTP non configuré

    def test_stop_request(self):
        settings_service.set_setting("messaging_cap_email", "100")
        rows = [ms.Recipient(self._client(f"S{i}", email=f"s{i}@x.com"), f"S{i}", "", f"s{i}@x.com", 0) for i in range(4)]
        out = []
        res = ms.send_email_campaign(rows, "Obj", "Msg", campaign="c2", sender=lambda *a: out.append(a), delay=0, should_stop=lambda: len(out) >= 2)
        self.assertTrue(res["stopped"])
        self.assertEqual(len(out), 2)

    def test_email_config_roundtrip(self):
        self.assertFalse(ms.email_configured())
        ms.save_email_config(host="smtp.example.com", port=465, security="ssl", user="me@example.com", password="secret", from_name="Boutique")
        self.assertTrue(ms.email_configured())
        with self.assertRaises(ValueError):
            ms.save_email_config(host="h", port=1, security="clair", user="u", password="p", from_name="")


if __name__ == "__main__":
    unittest.main()
