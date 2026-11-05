"""Тесты сборки базы знаний из исправленного razbor.md."""

import os
import subprocess
import sys
import tempfile
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKRIPT = os.path.join(KOREN, "skills", "sborka-bazy", "scripts", "sobrat.py")
PRIMER = os.path.join(KOREN, "examples", "razbor-primer.md")
sys.path.insert(0, os.path.dirname(SKRIPT))

import sobrat  # noqa: E402


def primer_tekst():
    with open(PRIMER, encoding="utf-8") as f:
        return f.read()


TEMA = """## Тема: Запись
- [x] в базу

### Как спрашивают
- «Как записаться?»

### Ответы из переписки
- 2026-07-01: «Напишите в этот чат.»

### Пометки
{pometki}

### Ответ для базы
{otvet}
"""


def odna_tema(otvet="Напишите в этот чат.", pometki=""):
    return "# Разбор переписки: Тест\n\n" + TEMA.format(otvet=otvet, pometki=pometki)


class TestChtenie(unittest.TestCase):
    def setUp(self):
        self.nazvanie, self.temy = sobrat.prochitat_razbor(primer_tekst())

    def test_nazvanie_iz_zagolovka(self):
        self.assertEqual(self.nazvanie, "Учебная студия")

    def test_tri_temy_bez_voprosov_bez_otveta(self):
        self.assertEqual([t["nazvanie"] for t in self.temy], ["Цена абонемента", "Оплата частями", "Парковка"])

    def test_galochki_latinskaya_i_russkaya_h(self):
        self.assertEqual([t["v_bazu"] for t in self.temy], [True, True, False])

    def test_kak_sprashivayut_i_otvet(self):
        t = self.temy[0]
        self.assertEqual(t["kak_sprashivayut"], ["Сколько стоит абонемент на месяц?", "А по цене что?"])
        self.assertEqual(t["otvet"], "Абонемент на месяц 4 500 ₽, восемь занятий.")

    def test_pometki(self):
        self.assertEqual(self.temy[2]["pometki"], ["⚠️ ответа нет"])


class TestProverka(unittest.TestCase):
    def problemy(self, tekst, **kw):
        _, temy = sobrat.prochitat_razbor(tekst)
        return sobrat.proverit(temy, **kw)

    def test_primer_bez_problem(self):
        self.assertEqual(self.problemy(primer_tekst()), [])

    def test_net_otveta(self):
        p = self.problemy(odna_tema(otvet="‹впишите ответ›"))
        self.assertEqual(len(p), 1)
        self.assertIn("«Запись»", p[0])
        self.assertIn("нет ответа", p[0])

    def test_pustoy_otvet(self):
        self.assertEqual(len(self.problemy(odna_tema(otvet=""))), 1)

    def test_nereshennaya_pometka(self):
        p = self.problemy(odna_tema(pometki="- ⚠️ ответы расходятся: 4 000 и 4 500"))
        self.assertEqual(len(p), 1)
        self.assertIn("ответы расходятся", p[0])

    def test_metka_skrytyh_dannyh_v_otvete(self):
        p = self.problemy(odna_tema(otvet="Пишите на [почта]"))
        self.assertEqual(len(p), 1)
        self.assertIn("[почта]", p[0])
        self.assertIn("в ответе", p[0])
        self.assertIn("контакт", p[0])

    def test_metka_skrytyh_dannyh_v_voprose(self):
        tekst = odna_tema().replace("«Как записаться?»", "«Как записаться? Мой телефон [телефон]»")
        p = self.problemy(tekst)
        self.assertEqual(len(p), 1)
        self.assertIn("[телефон]", p[0])
        self.assertIn("«Как спрашивают»", p[0])
        self.assertIn("удалите", p[0])
        self.assertNotIn("контакт компании", p[0])

    def test_nastoyashchiy_telefon_v_otvete(self):
        p = self.problemy(odna_tema(otvet="Звоните +7 000 111-22-33"))
        self.assertEqual(len(p), 1)
        self.assertIn("--kontakty-ok", p[0])

    def test_kontakt_kompanii_razreshen(self):
        self.assertEqual(self.problemy(odna_tema(otvet="Звоните +7 000 111-22-33"), kontakty_ok=True), [])

    def test_nichego_ne_otmecheno(self):
        tekst = odna_tema().replace("- [x] в базу", "- [ ] в базу")
        p = self.problemy(tekst)
        self.assertEqual(len(p), 1)
        self.assertIn("не отмечено", p[0])


class TestSborka(unittest.TestCase):
    def setUp(self):
        self.nazvanie, self.temy = sobrat.prochitat_razbor(primer_tekst())

    def test_dokument(self):
        doc = sobrat.sobrat(self.nazvanie, self.temy, data="2026-11-05")
        self.assertTrue(doc.startswith("# База знаний: Учебная студия\n"))
        self.assertIn("Собрано из разбора переписки 2026-11-05. Тем: 2.", doc)
        self.assertIn("## Цена абонемента\n\nКак спрашивают: «Сколько стоит абонемент на месяц?»; «А по цене что?»\n\n"
                      "Абонемент на месяц 4 500 ₽, восемь занятий.", doc)
        self.assertIn("## Оплата частями", doc)
        self.assertNotIn("Парковка", doc)
        self.assertNotIn("4 000", doc)

    def test_imya_fayla_latinitsey(self):
        self.assertEqual(sobrat.imya_fayla("Цена абонемента"), "tsena-abonementa.md")
        self.assertEqual(sobrat.imya_fayla("Оплата: частями!"), "oplata-chastyami.md")


class TestKomanda(unittest.TestCase):
    def zapustit(self, *argumenty):
        return subprocess.run([sys.executable, SKRIPT, *argumenty], capture_output=True, text=True, encoding="utf-8")

    def test_odin_fayl(self):
        with tempfile.TemporaryDirectory() as papka:
            vyhod = os.path.join(papka, "baza-znaniy.md")
            r = self.zapustit(PRIMER, "-o", vyhod)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(vyhod))
        self.assertIn("Тем в базе: 2", r.stdout)

    def test_papka_po_temam(self):
        with tempfile.TemporaryDirectory() as papka:
            r = self.zapustit(PRIMER, "--papka", papka)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(os.listdir(papka)), ["oplata-chastyami.md", "tsena-abonementa.md"])

    def test_problemy_ostanavlivayut_sborku(self):
        with tempfile.TemporaryDirectory() as papka:
            razbor = os.path.join(papka, "razbor.md")
            with open(razbor, "w", encoding="utf-8") as f:
                f.write(odna_tema(otvet="‹впишите ответ›"))
            vyhod = os.path.join(papka, "baza-znaniy.md")
            r = self.zapustit(razbor, "-o", vyhod)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(os.path.exists(vyhod))
        self.assertIn("нет ответа", r.stderr)


if __name__ == "__main__":
    unittest.main()
