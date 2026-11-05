"""Тесты скрипта разбора переписки. Запуск: python3 -m unittest discover -s tests -v"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKRIPT = os.path.join(KOREN, "skills", "razbor-perepiski", "scripts", "razobrat.py")
PRIMERY = os.path.join(KOREN, "examples")
sys.path.insert(0, os.path.dirname(SKRIPT))

import razobrat  # noqa: E402


def primer(imya):
    return os.path.join(PRIMERY, imya)


class TestFormat(unittest.TestCase):
    def test_uznaet_telegram(self):
        self.assertEqual(razobrat.opredelit_format(primer("telegram-result.json")), "telegram")

    def test_uznaet_whatsapp_iphone_i_android(self):
        self.assertEqual(razobrat.opredelit_format(primer("whatsapp-iphone.txt")), "whatsapp")
        self.assertEqual(razobrat.opredelit_format(primer("whatsapp-android.txt")), "whatsapp")

    def test_uznaet_csv(self):
        self.assertEqual(razobrat.opredelit_format(primer("crm-cp1251.csv")), "csv")

    def test_uznaet_html_telegram_po_papke_i_po_faylu(self):
        self.assertEqual(razobrat.opredelit_format(primer("telegram-html")), "telegram-html")
        self.assertEqual(razobrat.opredelit_format(primer("telegram-html/messages.html")), "telegram-html")

    def test_papka_s_result_json(self):
        with tempfile.TemporaryDirectory() as papka:
            with open(primer("telegram-result.json"), encoding="utf-8") as f, \
                    open(os.path.join(papka, "result.json"), "w", encoding="utf-8") as g:
                g.write(f.read())
            self.assertEqual(razobrat.opredelit_format(papka), "telegram")
            soobshcheniya, _ = razobrat.prochitat(papka)
        self.assertEqual(len(soobshcheniya), 5)


class TestData(unittest.TestCase):
    def test_raznye_formaty_daty(self):
        n = razobrat.normalizovat_datu
        self.assertEqual(n("2026-07-01T10:00:00"), "2026-07-01 10:00")
        self.assertEqual(n("01.07.2026, 10:01:15"), "2026-07-01 10:01")
        self.assertEqual(n("01.07.2026 9:05"), "2026-07-01 09:05")
        self.assertEqual(n("10/28/26, 2:05 PM"), "2026-10-28 14:05")
        self.assertEqual(n("28/10/2026, 14:05"), "2026-10-28 14:05")

    def test_data_slovami_iz_telegram_dlya_mac(self):
        n = razobrat.normalizovat_datu
        self.assertEqual(n("5 мая 2026, 12:11:12"), "2026-05-05 12:11")
        self.assertEqual(n("12 июня 2020, 13:51:31"), "2020-06-12 13:51")
        self.assertEqual(n("3 December 2025, 9:05:00"), "2025-12-03 09:05")
        self.assertEqual(n("05.05.2026 13:00:00 UTC+05:00"), "2026-05-05 13:00")

    def test_neponyatnaya_data_ostaetsya_kak_est(self):
        self.assertEqual(razobrat.normalizovat_datu("вчера"), "вчера")


class TestTelegram(unittest.TestCase):
    def setUp(self):
        self.soobshcheniya, self.stat = razobrat.prochitat(primer("telegram-result.json"))

    def test_pervoe_soobshchenie(self):
        s = self.soobshcheniya[0]
        self.assertEqual(s["data"], "2026-07-01 10:00")
        self.assertEqual(s["avtor"], "Ирина Тестова")
        self.assertEqual(s["tekst"], "Здравствуйте! Сколько стоит абонемент на месяц?")

    def test_tekst_iz_chastey_skleivaetsya(self):
        teksty = [s["tekst"] for s in self.soobshcheniya]
        self.assertIn("А можно оплатить частями? Мой телефон +7 000 111-22-33, перезвоните", teksty)

    def test_sluzhebnye_golosovye_i_stikery_ne_popadayut_v_tekst(self):
        self.assertEqual(len(self.soobshcheniya), 5)

    def test_propushchennoe_schitaetsya(self):
        self.assertEqual(self.stat["propushcheno"], {"голосовое": 1, "стикер": 1, "фото": 1})
        self.assertEqual(self.stat["sluzhebnyh"], 1)

    def test_podpis_k_foto_ostaetsya(self):
        self.assertEqual(self.soobshcheniya[-1]["tekst"], "Вот мой чек")

    def test_polnaya_vygruzka_akkaunta(self):
        with open(primer("telegram-result.json"), encoding="utf-8") as f:
            chat = json.load(f)
        with tempfile.TemporaryDirectory() as papka:
            put = os.path.join(papka, "result.json")
            with open(put, "w", encoding="utf-8") as f:
                json.dump({"chats": {"list": [chat, chat]}}, f, ensure_ascii=False)
            soobshcheniya, _ = razobrat.prochitat(put)
        self.assertEqual(len(soobshcheniya), 10)


class TestTelegramHtml(unittest.TestCase):
    def setUp(self):
        self.soobshcheniya, self.stat = razobrat.prochitat(primer("telegram-html"))

    def test_soobshcheniya_iz_dvuh_faylov_po_poryadku(self):
        self.assertEqual([s["tekst"] for s in self.soobshcheniya], [
            "Здравствуйте! Сколько стоит абонемент?",
            "И есть ли рассрочка?\nХочу частями",
            "Абонемент 4 000 ₽, можно в два платежа. Пишите irina.testova@example.com",
            "А парковка есть?",
            "Вот схема проезда",
        ])

    def test_avtor_prodolzheniya_beretsya_iz_predydushchego(self):
        self.assertEqual([s["avtor"] for s in self.soobshcheniya], [
            "Ирина Тестова", "Ирина Тестова", "Студия Учебная", "Пётр Пробный", "Студия Учебная",
        ])

    def test_daty(self):
        self.assertEqual(self.soobshcheniya[0]["data"], "2026-05-05 12:11")
        self.assertEqual(self.soobshcheniya[-1]["data"], "2026-05-05 13:00")

    def test_otvet_na_soobshchenie(self):
        self.assertEqual(self.soobshcheniya[2]["otvet_na"], "11")
        self.assertEqual(self.soobshcheniya[0]["id"], "11")

    def test_propushcheno_i_sluzhebnye(self):
        self.assertEqual(self.stat["propushcheno"], {"голосовое": 1, "пересланное": 1, "фото": 1})
        self.assertEqual(self.stat["sluzhebnyh"], 2)

    def test_otvet_vidno_v_razmetke(self):
        razmecheno, _ = razobrat.razmetit(self.soobshcheniya, vladelcy=["Студия Учебная"])
        self.assertEqual(
            razmecheno[2]["tekst"],
            "[↪ Клиент 1: «Здравствуйте! Сколько стоит абонемент?»] "
            "Абонемент 4 000 ₽, можно в два платежа. Пишите [почта]",
        )

    def test_dlinnaya_tsitata_obrezaetsya(self):
        soobshcheniya = [
            {"id": "1", "data": "2026-05-05 10:00", "avtor": "Клиентка", "tekst": "а" * 100},
            {"id": "2", "data": "2026-05-05 10:01", "avtor": "Студия", "tekst": "Ответ", "otvet_na": "1"},
        ]
        razmecheno, _ = razobrat.razmetit(soobshcheniya, vladelcy=["Студия"])
        self.assertEqual(razmecheno[1]["tekst"], "[↪ Клиент 1: «" + "а" * 60 + "…»] Ответ")


class TestWhatsApp(unittest.TestCase):
    def test_iphone_mnogostrochnoe_soobshchenie(self):
        soobshcheniya, _ = razobrat.prochitat(primer("whatsapp-iphone.txt"))
        teksty = [s["tekst"] for s in soobshcheniya]
        self.assertIn("Да, в субботу в 11:00.\nИ в воскресенье в 12:00.", teksty)

    def test_iphone_shifrovanie_i_audio_ne_v_tekste(self):
        soobshcheniya, stat = razobrat.prochitat(primer("whatsapp-iphone.txt"))
        self.assertEqual(len(soobshcheniya), 3)
        self.assertEqual(stat["propushcheno"], {"аудио": 1})
        self.assertEqual(stat["sluzhebnyh"], 1)

    def test_iphone_avtor_i_data(self):
        soobshcheniya, _ = razobrat.prochitat(primer("whatsapp-iphone.txt"))
        self.assertEqual(soobshcheniya[0]["avtor"], "Пётр Пробный")
        self.assertEqual(soobshcheniya[0]["data"], "2026-07-01 10:01")

    def test_android(self):
        soobshcheniya, stat = razobrat.prochitat(primer("whatsapp-android.txt"))
        self.assertEqual([s["avtor"] for s in soobshcheniya], ["Пётр Пробный", "Студия Учебная"])
        self.assertEqual(stat["propushcheno"], {"медиафайл": 1})
        self.assertEqual(stat["sluzhebnyh"], 1)


class TestCsv(unittest.TestCase):
    def test_info_pokazyvaet_kolonki_i_podskazku(self):
        info = razobrat.info_csv(primer("crm-cp1251.csv"))
        self.assertEqual(info["kolonki"], ["Дата", "Автор", "Направление", "Текст"])
        self.assertEqual(info["razdelitel"], ";")
        self.assertEqual(info["kodirovka"], "cp1251")
        self.assertEqual(info["podskazka"], {"avtor": "Автор", "data": "Дата", "tekst": "Текст"})
        self.assertEqual(len(info["primer_strok"]), 3)

    def test_chtenie_po_kolonkam(self):
        soobshcheniya, _ = razobrat.prochitat(
            primer("crm-cp1251.csv"), kolonki={"avtor": "Автор", "data": "Дата", "tekst": "Текст"}
        )
        self.assertEqual(len(soobshcheniya), 3)
        self.assertEqual(soobshcheniya[1]["avtor"], "Менеджер Ольга")
        self.assertEqual(soobshcheniya[1]["data"], "2026-07-02 09:20")

    def test_bez_kolonok_ponyatnaya_oshibka(self):
        with self.assertRaises(razobrat.OshibkaRazbora) as oshibka:
            razobrat.prochitat(primer("crm-cp1251.csv"))
        self.assertIn("--info", str(oshibka.exception))


class TestMaski(unittest.TestCase):
    def test_telefony(self):
        for nomer in ["+7 000 111-22-33", "8 (000) 111-22-44", "+79001112233", "8-900-111-22-33"]:
            tekst, schet = razobrat.maskirovat(f"Звоните {nomer} вечером")
            self.assertEqual(tekst, "Звоните [телефон] вечером", nomer)
            self.assertEqual(schet["телефон"], 1)

    def test_tseny_i_vremya_ne_telefony(self):
        tekst, _ = razobrat.maskirovat("Абонемент 4 000 ₽, занятия в 19:00, 12.07.2026")
        self.assertEqual(tekst, "Абонемент 4 000 ₽, занятия в 19:00, 12.07.2026")

    def test_pochta_nik_i_ssylka_telegram(self):
        tekst, schet = razobrat.maskirovat("Пишите anna@example.com, @studia_uchebnaya или t.me/ivan_test")
        self.assertEqual(tekst, "Пишите [почта], [ник] или [ник]")
        self.assertEqual(schet, {"почта": 1, "ник": 2})


class TestRoli(unittest.TestCase):
    def setUp(self):
        soobshcheniya, _ = razobrat.prochitat(primer("telegram-result.json"))
        self.razmecheno, self.schet = razobrat.razmetit(soobshcheniya, vladelcy=["Студия Учебная"])

    def test_vladelec_i_klient(self):
        self.assertEqual(self.razmecheno[0]["rol"], "Клиент 1")
        self.assertEqual(self.razmecheno[1]["rol"], "Владелец")
        self.assertNotIn("avtor", self.razmecheno[0])

    def test_imena_uchastnikov_v_tekste_skryty(self):
        self.assertEqual(self.razmecheno[1]["tekst"], "Здравствуйте, [имя]! Абонемент на месяц 4 000 ₽, восемь занятий.")

    def test_maski_primeneny(self):
        teksty = " ".join(s["tekst"] for s in self.razmecheno)
        self.assertNotIn("+7 000", teksty)
        self.assertNotIn("@studia", teksty)
        self.assertEqual(self.schet["телефон"], 1)

    def test_obychnoe_slovo_iz_nika_ne_skryvaetsya(self):
        soobshcheniya = [
            {"data": "2026-05-05 10:00", "avtor": "Любовь Светлова", "tekst": "Любовь — это практика? любовь и любовь, и ещё раз любовь"},
            {"data": "2026-05-05 10:01", "avtor": "Ирина Тестова", "tekst": "Любовь Светлова, Ирина спрашивает про Ирину"},
            {"data": "2026-05-05 10:02", "avtor": "Студия", "tekst": "Ответ"},
        ]
        razmecheno, _ = razobrat.razmetit(soobshcheniya, vladelcy=["Студия"])
        self.assertEqual(razmecheno[0]["tekst"], "Любовь — это практика? любовь и любовь, и ещё раз любовь")
        self.assertEqual(razmecheno[1]["tekst"], "[имя], [имя] спрашивает про [имя]")

    def test_formy_obychnogo_slova_ne_skryvayutsya(self):
        soobshcheniya = [
            {"data": "2026-05-05 10:00", "avtor": "Добро Пожаловать", "tekst": "Привет"},
            {"data": "2026-05-05 10:01", "avtor": "Студия", "tekst": "Доброе утро! добрый день, доброго вечера, добрые люди"},
        ]
        razmecheno, _ = razobrat.razmetit(soobshcheniya, vladelcy=["Студия"])
        self.assertEqual(razmecheno[1]["tekst"], "Доброе утро! добрый день, доброго вечера, добрые люди")

    def test_neizvestnyy_vladelec_oshibka(self):
        soobshcheniya, _ = razobrat.prochitat(primer("telegram-result.json"))
        with self.assertRaises(razobrat.OshibkaRazbora):
            razobrat.razmetit(soobshcheniya, vladelcy=["Нет Такого"])


class TestKomanda(unittest.TestCase):
    def zapustit(self, *argumenty):
        return subprocess.run(
            [sys.executable, SKRIPT, *argumenty], capture_output=True, text=True, encoding="utf-8"
        )

    def test_info_telegram_spisok_uchastnikov(self):
        r = self.zapustit(primer("telegram-result.json"), "--info")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ирина Тестова: 3", r.stdout)
        self.assertIn("Студия Учебная: 2", r.stdout)

    def test_razbor_v_fayl(self):
        with tempfile.TemporaryDirectory() as papka:
            vyhod = os.path.join(papka, "perepiska.txt")
            r = self.zapustit(primer("telegram-result.json"), "--vladelec", "Студия Учебная", "-o", vyhod)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(vyhod, encoding="utf-8") as f:
                tekst = f.read()
        self.assertIn("2026-07-01 10:10 | Владелец | Да, можно в два платежа. Напишите на [почта] или [ник]", tekst)
        self.assertNotIn("Ирина", tekst)
        self.assertIn("голосовое: 1", r.stdout)

    def test_razbor_s_daty(self):
        r = self.zapustit(primer("whatsapp-iphone.txt"), "--vladelec", "Студия Учебная", "--s", "2026-07-02")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("нет сообщений", r.stderr)

    def test_csv_bez_kolonok(self):
        r = self.zapustit(primer("crm-cp1251.csv"), "--vladelec", "Менеджер Ольга")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--info", r.stderr)

    def test_csv_s_kolonkami(self):
        r = self.zapustit(
            primer("crm-cp1251.csv"), "--vladelec", "Менеджер Ольга",
            "--avtor", "Автор", "--data", "Дата", "--tekst", "Текст",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| Владелец | Расписание: пн, ср, пт в 19:00. Почта для вопросов [почта]", r.stdout)


if __name__ == "__main__":
    unittest.main()
