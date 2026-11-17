#!/usr/bin/env python3
"""Собирает документ базы знаний из razbor.md, который исправил человек.

В базу идут только темы с отметкой «- [x] в базу» и только «Ответ для базы».
Сначала проверка: если есть отмеченная тема без ответа, нерешённая пометка ⚠️
или личные данные, сборка останавливается и печатает список.

Только стандартная библиотека, Python 3.9 и новее.

    python3 sobrat.py razbor.md -o baza-znaniy.md
    python3 sobrat.py razbor.md --papka baza-znaniy

В режиме --papka скрипт помнит, какие файлы записал, в скрытом файле .sobrano.txt
внутри папки. Если при следующей сборке там остались файлы тем, которых больше нет
в базе, сборка останавливается: без --ochistit они ушли бы в бота. Чужие файлы
в папке скрипт не трогает.
"""

import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "razbor-perepiski", "scripts"))
from razobrat import MASKI  # noqa: E402

OTMETKA = re.compile(r"^-\s*(\[[xXхХ]\]|☑)\s*в базу", re.I)
METKA_SKRYTOGO = re.compile(r"\[(телефон|почта|ник|имя|карта)\]")


def prochitat_razbor(tekst):
    """Возвращает название из заголовка и список тем."""
    nazvanie = ""
    m = re.search(r"^# (.+)$", tekst, re.M)
    if m:
        nazvanie = re.sub(r"^Разбор переписки:?\s*", "", m.group(1).strip())
    temy = []
    for kusok in re.split(r"^## ", tekst, flags=re.M)[1:]:
        stroki = kusok.splitlines()
        zagolovok = stroki[0].strip()
        if not zagolovok.startswith("Тема:"):
            continue
        tema = {
            "nazvanie": zagolovok[len("Тема:"):].strip(),
            "v_bazu": False,
            "kak_sprashivayut": [],
            "pometki": [],
            "otvet": "",
        }
        razdel, otvet = None, []
        for stroka in stroki[1:]:
            chistaya = stroka.strip()
            if chistaya == "---":
                continue
            if chistaya.startswith("### "):
                razdel = chistaya[4:].strip().lower()
                continue
            if razdel is None:
                if OTMETKA.match(chistaya):
                    tema["v_bazu"] = True
            elif razdel == "как спрашивают" and chistaya.startswith("- "):
                tema["kak_sprashivayut"].append(chistaya[2:].strip().strip("«»\"").strip())
            elif razdel == "пометки" and chistaya.startswith("- "):
                tema["pometki"].append(chistaya[2:].strip())
            elif razdel == "ответ для базы":
                otvet.append(stroka.rstrip())
        tema["otvet"] = "\n".join(otvet).strip()
        temy.append(tema)
    return nazvanie, temy


def proverit(temy, kontakty_ok=False):
    """Список проблем, из-за которых собирать нельзя. Пустой список — можно."""
    otmecheno = [t for t in temy if t["v_bazu"]]
    if not otmecheno:
        return ["В разборе не отмечено ни одной темы: поставьте x в строке «- [ ] в базу» у нужных тем."]
    problemy = []
    for t in otmecheno:
        imya = f"Тема «{t['nazvanie']}»"
        otvet = t["otvet"]
        if not otvet or "‹" in otvet:
            problemy.append(f"{imya}: нет ответа для базы. Впишите ответ или снимите отметку «в базу».")
        for pometka in t["pometki"]:
            if pometka.startswith("⚠"):
                problemy.append(f"{imya}: не решена пометка «{pometka}». Удалите строку, когда решите.")
        for metka in sorted(set(METKA_SKRYTOGO.findall(otvet))):
            problemy.append(f"{imya}: в ответе осталась метка [{metka}]. Впишите вместо неё свой контакт или уберите метку.")
        for metka in sorted(set(METKA_SKRYTOGO.findall(" ".join(t["kak_sprashivayut"])))):
            problemy.append(
                f"{imya}: в «Как спрашивают» осталась метка [{metka}]. Это данные клиента: удалите метку из вопроса."
            )
        if not kontakty_ok:
            vidy = sorted({vid for vid, shablon in MASKI if shablon.search(otvet)})
            for vid in vidy:
                problemy.append(
                    f"{imya}: в ответе есть {vid}. Если это контакт компании, а не клиента, "
                    "запустите сборку с --kontakty-ok."
                )
        vidy_v_voprosah = sorted({vid for vid, shablon in MASKI for k in t["kak_sprashivayut"] if shablon.search(k)})
        for vid in vidy_v_voprosah:
            problemy.append(f"{imya}: в «Как спрашивают» есть {vid}. Уберите его из формулировки.")
    return problemy


def tekst_temy(t, uroven="##"):
    stroki = [f"{uroven} {t['nazvanie']}", ""]
    if t["kak_sprashivayut"]:
        stroki += ["Как спрашивают: " + "; ".join(f"«{k}»" for k in t["kak_sprashivayut"]), ""]
    stroki += [t["otvet"], ""]
    return stroki


def sobrat(nazvanie, temy, data=None):
    data = data or date.today().isoformat()
    otmecheno = [t for t in temy if t["v_bazu"]]
    stroki = [f"# База знаний: {nazvanie}" if nazvanie else "# База знаний", ""]
    stroki += [f"Собрано из разбора переписки {data}. Тем: {len(otmecheno)}.", ""]
    for t in otmecheno:
        stroki += tekst_temy(t)
    return "\n".join(stroki).rstrip() + "\n"


TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
     "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))


def imya_fayla(nazvanie):
    lat = "".join(TRANSLIT.get(b, b) for b in nazvanie.lower())
    lat = re.sub(r"[^a-z0-9]+", "-", lat).strip("-")
    return (lat or "tema") + ".md"


ZAPISANO = ".sobrano.txt"


def imena_fayla_po_temam(temy):
    zanyato = []
    for t in temy:
        osnova = imya_fayla(t["nazvanie"])
        imya, n = osnova, 2
        while imya in zanyato:
            imya = osnova[:-3] + f"-{n}.md"
            n += 1
        zanyato.append(imya)
    return zanyato


def starye_fayly(papka, novye):
    """Файлы прошлой сборки, которых нет среди новых и которые ещё лежат в папке."""
    put = os.path.join(papka, ZAPISANO)
    if not os.path.isfile(put):
        return []
    with open(put, encoding="utf-8") as f:
        proshlye = [s.strip() for s in f if s.strip()]
    return [imya for imya in proshlye
            if imya not in novye and os.path.basename(imya) == imya and os.path.isfile(os.path.join(papka, imya))]


def main(argv=None):
    for potok in (sys.stdout, sys.stderr):
        if hasattr(potok, "reconfigure"):
            potok.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Собирает базу знаний из исправленного razbor.md.")
    p.add_argument("razbor", help="исправленный файл razbor.md")
    p.add_argument("-o", help="файл базы знаний, по умолчанию baza-znaniy.md рядом с разбором")
    p.add_argument("--papka", help="вместо одного файла — папка, по файлу на тему")
    p.add_argument("--ochistit", action="store_true",
                   help="в режиме --papka удалить файлы тем из прошлой сборки, которых нет в новой")
    p.add_argument("--kontakty-ok", action="store_true", help="телефоны и почты в ответах — контакты компании")
    args = p.parse_args(argv)

    if not os.path.isfile(args.razbor):
        print(f"Ошибка: файл не найден: {args.razbor}", file=sys.stderr)
        return 2
    with open(args.razbor, encoding="utf-8-sig") as f:
        nazvanie, temy = prochitat_razbor(f.read())
    if not temy:
        print("Ошибка: в файле нет ни одной темы «## Тема: …». Это точно разбор переписки?", file=sys.stderr)
        return 2
    problemy = proverit(temy, kontakty_ok=args.kontakty_ok)
    if problemy:
        print("Сборка остановлена, исправьте в разборе:", file=sys.stderr)
        for n, problema in enumerate(problemy, 1):
            print(f"{n}. {problema}", file=sys.stderr)
        return 2

    otmecheno = [t for t in temy if t["v_bazu"]]
    if args.papka:
        imena = imena_fayla_po_temam(otmecheno)
        starye = starye_fayly(args.papka, imena) if os.path.isdir(args.papka) else []
        if starye and not args.ochistit:
            print(f"Сборка остановлена: в папке {args.papka} остались файлы прошлой сборки,"
                  " этих тем в новой базе нет:", file=sys.stderr)
            for imya in starye:
                print(f"- {imya}", file=sys.stderr)
            print("Если их оставить, они уйдут в бота. Удалите их сами"
                  " или запустите сборку ещё раз с --ochistit.", file=sys.stderr)
            return 2
        os.makedirs(args.papka, exist_ok=True)
        for imya in starye:
            os.remove(os.path.join(args.papka, imya))
        for t, imya in zip(otmecheno, imena):
            with open(os.path.join(args.papka, imya), "w", encoding="utf-8") as f:
                f.write("\n".join(tekst_temy(t, "#")).rstrip() + "\n")
        with open(os.path.join(args.papka, ZAPISANO), "w", encoding="utf-8") as f:
            f.write("".join(imya + "\n" for imya in imena))
        if starye:
            print("Удалены файлы прошлой сборки: " + ", ".join(starye))
        kuda = args.papka
    else:
        kuda = args.o or os.path.join(os.path.dirname(os.path.abspath(args.razbor)), "baza-znaniy.md")
        with open(kuda, "w", encoding="utf-8") as f:
            f.write(sobrat(nazvanie, temy))
    print(f"Тем в базе: {len(otmecheno)}. Не вошло: {len(temy) - len(otmecheno)}. Записано в {kuda}")
    napominaniya = [f"«{t['nazvanie']}»: {p}" for t in otmecheno for p in t["pometki"] if p.startswith("ℹ")]
    if napominaniya:
        print("Напоминания из пометок:")
        for stroka in napominaniya:
            print(f"- {stroka}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
