#!/usr/bin/env python3
"""Готовит выгрузку переписки к разбору: читает Telegram, WhatsApp или CSV,
скрывает телефоны, почты, ники и имена, заменяет участников ролями.

Только стандартная библиотека, Python 3.9 и новее.

    python3 razobrat.py ВЫГРУЗКА --info
    python3 razobrat.py ВЫГРУЗКА --vladelec "Имя как в чате" -o perepiska.txt
    python3 razobrat.py ВЫГРУЗКА.csv --info
    python3 razobrat.py ВЫГРУЗКА.csv --avtor Автор --data Дата --tekst Текст --vladelec "Менеджер" -o perepiska.txt
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime


class OshibkaRazbora(Exception):
    """Понятная человеку ошибка: печатается без трассировки."""


# ---------- формат и даты ----------

STROKA_WHATSAPP = re.compile(
    r"^[‎‏]?\[?(\d{1,2}[./]\d{1,2}[./]\d{2,4}),?\s+"
    r"(\d{1,2}:\d{2}(?::\d{2})?(?:[\s ]?[AaPp]\.?\s?[Mm]\.?)?)\]?\s+(?:-\s+)?(.*)$"
)


def opredelit_format(put):
    rasshirenie = os.path.splitext(put)[1].lower()
    if rasshirenie == ".json":
        return "telegram"
    if rasshirenie == ".csv":
        return "csv"
    if rasshirenie == ".txt":
        with open(put, encoding="utf-8-sig", errors="replace") as f:
            for _ in range(20):
                stroka = f.readline()
                if not stroka:
                    break
                if STROKA_WHATSAPP.match(stroka.strip()):
                    return "whatsapp"
    raise OshibkaRazbora(
        f"Не понимаю формат файла {os.path.basename(put)}. Подходят: result.json из Telegram Desktop, "
        ".txt из «Экспорт чата» WhatsApp, .csv из CRM."
    )


DATA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})")
DATA_CHISLA = re.compile(
    r"^(\d{1,2})([./])(\d{1,2})\2(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?[\s ]*([AaPp])?\.?\s?[Mm]?\.?"
)


def normalizovat_datu(stroka):
    """Любую дату из выгрузок приводит к виду ГГГГ-ММ-ДД ЧЧ:ММ. Непонятную оставляет как есть."""
    s = stroka.strip().replace(" ", " ")
    m = DATA_ISO.match(s)
    if m:
        god, mesyac, den, chas, minuta = (int(x) for x in m.groups())
    else:
        m = DATA_CHISLA.match(s)
        if not m:
            return stroka
        a, razdelitel, b, god, chas, minuta, ampm = m.groups()
        a, b, god, chas, minuta = int(a), int(b), int(god), int(chas), int(minuta)
        if razdelitel == "/" and a <= 12:
            mesyac, den = a, b  # американская запись: месяц/день
        else:
            den, mesyac = a, b
        if god < 100:
            god += 2000
        if ampm:
            if ampm.lower() == "p" and chas < 12:
                chas += 12
            if ampm.lower() == "a" and chas == 12:
                chas = 0
    try:
        return datetime(god, mesyac, den, chas, minuta).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stroka


# ---------- Telegram ----------

MEDIA_TELEGRAM = {
    "voice_message": "голосовое",
    "video_message": "видеосообщение",
    "sticker": "стикер",
    "animation": "гиф",
    "video_file": "видео",
    "audio_file": "аудио",
}


def skleit_tekst(tekst):
    if isinstance(tekst, str):
        return tekst
    if isinstance(tekst, list):
        return "".join(chast if isinstance(chast, str) else chast.get("text", "") for chast in tekst)
    return ""


def chitat_telegram(put):
    with open(put, encoding="utf-8-sig") as f:
        dannye = json.load(f)
    if isinstance(dannye, dict) and "chats" in dannye:
        chaty = dannye["chats"].get("list", [])
    else:
        chaty = [dannye]
    soobshcheniya, propushcheno, sluzhebnyh = [], Counter(), 0
    for chat in chaty:
        for s in chat.get("messages", []):
            if s.get("type") != "message":
                sluzhebnyh += 1
                continue
            vid = MEDIA_TELEGRAM.get(s.get("media_type"))
            if vid is None and "photo" in s:
                vid = "фото"
            if vid is None and "file" in s:
                vid = "файл"
            if vid:
                propushcheno[vid] += 1
            tekst = skleit_tekst(s.get("text")).strip()
            if tekst:
                soobshcheniya.append({
                    "data": normalizovat_datu(s.get("date", "")),
                    "avtor": s.get("from") or "Удалённый аккаунт",
                    "tekst": tekst,
                })
    return soobshcheniya, propushcheno, sluzhebnyh


# ---------- WhatsApp ----------

MEDIA_WHATSAPP = [
    (re.compile(r"^<?(без медиафайлов|media omitted)>?$", re.I), "медиафайл"),
    (re.compile(r"^(аудио|audio)\b", re.I), "аудио"),
    (re.compile(r"^(изображение|image|фото)\b", re.I), "фото"),
    (re.compile(r"^(видео|video)\b", re.I), "видео"),
    (re.compile(r"^(стикер|sticker)\b", re.I), "стикер"),
    (re.compile(r"^(gif|гиф)\b", re.I), "гиф"),
    (re.compile(r"^(документ|document)\b", re.I), "документ"),
]
VLOZHENIE_WHATSAPP = re.compile(r"^<(attached|прикреплено|вложение):\s*(.*)>$", re.I)


def vid_media_whatsapp(syroy_tekst):
    """Возвращает вид вложения, 'служебное' или None, если это обычный текст."""
    tekst = syroy_tekst.strip().lstrip("‎‏").strip()
    m = VLOZHENIE_WHATSAPP.match(tekst)
    if m:
        imya = m.group(2).upper()
        for metka, vid in (("PHOTO", "фото"), ("AUDIO", "аудио"), ("VIDEO", "видео"), ("STICKER", "стикер")):
            if metka in imya:
                return vid
        return "файл"
    if syroy_tekst.startswith(("‎", "‏")) or tekst.startswith("<"):
        for shablon, vid in MEDIA_WHATSAPP:
            if shablon.match(tekst) and len(tekst) < 60:
                return vid
    if syroy_tekst.startswith(("‎", "‏")):
        return "служебное"
    return None


def chitat_whatsapp(put):
    soobshcheniya, propushcheno, sluzhebnyh = [], Counter(), 0
    tekushchee = None
    with open(put, encoding="utf-8-sig", errors="replace") as f:
        for stroka in f:
            stroka = stroka.rstrip("\r\n")
            m = STROKA_WHATSAPP.match(stroka)
            if not m:
                if tekushchee is not None:
                    tekushchee["tekst"] += "\n" + stroka
                continue
            data, vremya, ostatok = m.groups()
            tekushchee = None
            if ": " not in ostatok:
                sluzhebnyh += 1
                continue
            avtor, tekst = ostatok.split(": ", 1)
            vid = vid_media_whatsapp(tekst)
            if vid == "служебное":
                sluzhebnyh += 1
                continue
            if vid:
                propushcheno[vid] += 1
                continue
            tekushchee = {
                "data": normalizovat_datu(f"{data}, {vremya}"),
                "avtor": avtor.strip().lstrip("‎"),
                "tekst": tekst,
            }
            soobshcheniya.append(tekushchee)
    for s in soobshcheniya:
        s["tekst"] = s["tekst"].strip()
    return soobshcheniya, propushcheno, sluzhebnyh


# ---------- CSV ----------

PODSKAZKI_CSV = {
    "avtor": ["автор", "от кого", "отправител", "сотрудник", "author", "from", "sender", "user"],
    "data": ["дата", "время", "date", "time", "created", "создан"],
    "tekst": ["текст", "сообщени", "message", "text", "body", "содержан", "комментари"],
}


def otkryt_csv(put):
    with open(put, "rb") as f:
        syrye = f.read()
    try:
        tekst, kodirovka = syrye.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        tekst, kodirovka = syrye.decode("cp1251"), "cp1251"
    obrazec = tekst[:5000]
    try:
        razdelitel = csv.Sniffer().sniff(obrazec, delimiters=";,\t").delimiter
    except csv.Error:
        pervaya = obrazec.splitlines()[0] if obrazec else ""
        razdelitel = ";" if pervaya.count(";") >= pervaya.count(",") else ","
    chitatel = csv.DictReader(io.StringIO(tekst, newline=""), delimiter=razdelitel)
    stroki = list(chitatel)
    kolonki = list(chitatel.fieldnames or [])
    return stroki, kolonki, razdelitel, kodirovka


def info_csv(put):
    stroki, kolonki, razdelitel, kodirovka = otkryt_csv(put)
    podskazka, zanyato = {}, set()
    for rol, slova in PODSKAZKI_CSV.items():
        for kolonka in kolonki:
            if kolonka not in zanyato and any(slovo in kolonka.lower() for slovo in slova):
                podskazka[rol] = kolonka
                zanyato.add(kolonka)
                break
    primer = [[maskirovat(s.get(k) or "")[0] for k in kolonki] for s in stroki[:3]]
    return {
        "kolonki": kolonki,
        "razdelitel": razdelitel,
        "kodirovka": kodirovka,
        "podskazka": podskazka,
        "primer_strok": primer,
        "strok": len(stroki),
    }


def chitat_csv(put, kolonki):
    nuzhno = ("avtor", "data", "tekst")
    if not kolonki or any(not kolonki.get(k) for k in nuzhno):
        raise OshibkaRazbora(
            "Для CSV нужно сказать, в какой колонке автор, дата и текст. Сначала запустите с --info, "
            "потом укажите --avtor, --data и --tekst."
        )
    stroki, imena, _, _ = otkryt_csv(put)
    for k in nuzhno:
        if kolonki[k] not in imena:
            raise OshibkaRazbora(f"В файле нет колонки «{kolonki[k]}». Есть: {', '.join(imena)}.")
    soobshcheniya = []
    for s in stroki:
        tekst = (s.get(kolonki["tekst"]) or "").strip()
        if tekst:
            soobshcheniya.append({
                "data": normalizovat_datu(s.get(kolonki["data"]) or ""),
                "avtor": (s.get(kolonki["avtor"]) or "").strip() or "Без имени",
                "tekst": tekst,
            })
    return soobshcheniya, Counter(), 0


# ---------- общее ----------

def prochitat(put, fmt=None, kolonki=None):
    if not os.path.isfile(put):
        raise OshibkaRazbora(f"Файл не найден: {put}")
    fmt = fmt or opredelit_format(put)
    if fmt == "telegram":
        soobshcheniya, propushcheno, sluzhebnyh = chitat_telegram(put)
    elif fmt == "whatsapp":
        soobshcheniya, propushcheno, sluzhebnyh = chitat_whatsapp(put)
    elif fmt == "csv":
        soobshcheniya, propushcheno, sluzhebnyh = chitat_csv(put, kolonki)
    else:
        raise OshibkaRazbora(f"Неизвестный формат: {fmt}")
    return soobshcheniya, {"format": fmt, "propushcheno": dict(propushcheno), "sluzhebnyh": sluzhebnyh}


MASKI = [
    ("почта", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("ник", re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/[\w+]+", re.I)),
    ("ник", re.compile(r"(?<![\w@])@[A-Za-z]\w{3,31}")),
    ("карта", re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)")),
    ("телефон", re.compile(r"(?<![\w+])(?:\+7|8|7)?[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\w)")),
    ("телефон", re.compile(r"(?<!\w)\+\d(?:[\s()-]*\d){9,14}(?!\w)")),
]


def maskirovat(tekst):
    """Скрывает почты, ники, номера карт и телефоны. Возвращает текст и счёт скрытого."""
    schet = Counter()
    for vid, shablon in MASKI:
        tekst, n = shablon.subn(f"[{vid}]", tekst)
        schet[vid] += n
    return tekst, {k: v for k, v in schet.items() if v}


def shablon_imeni(imena_klientov, imena_vseh):
    """Полные имена всех участников и отдельные слова имён клиентов, с падежными окончаниями."""
    chasti = set()
    for imya in imena_vseh:
        if len(imya) >= 3:
            chasti.add(re.escape(imya))
    for imya in imena_klientov:
        for slovo in re.findall(r"\w+", imya):
            if len(slovo) >= 4 and slovo[0].isupper():
                chasti.add(re.escape(slovo[:-1]) + r"\w{0,3}")
            elif len(slovo) == 3 and slovo[0].isupper():
                chasti.add(re.escape(slovo))
    if not chasti:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(sorted(chasti, key=len, reverse=True)) + r")(?!\w)")


def razmetit(soobshcheniya, vladelcy):
    avtory = []
    for s in soobshcheniya:
        if s["avtor"] not in avtory:
            avtory.append(s["avtor"])
    vladelcy = [v.strip() for v in vladelcy if v and v.strip()]
    if not vladelcy or not any(v in avtory for v in vladelcy):
        raise OshibkaRazbora(
            "Не нашёл владельца среди участников. Участники: " + ", ".join(avtory)
            + ". Укажите --vladelec точно как в выгрузке."
        )
    roli, nomer = {}, 0
    for avtor in avtory:
        if avtor in vladelcy:
            roli[avtor] = "Владелец"
        else:
            nomer += 1
            roli[avtor] = f"Клиент {nomer}"
    klienty = [a for a in avtory if a not in vladelcy]
    shablon = shablon_imeni(klienty, avtory)
    itog, schet = [], Counter()
    for s in soobshcheniya:
        tekst, maski = maskirovat(s["tekst"])
        schet.update(maski)
        if shablon:
            tekst, n = shablon.subn("[имя]", tekst)
            schet["имя"] += n
        itog.append({"data": s["data"], "rol": roli[s["avtor"]], "tekst": tekst})
    return itog, {k: v for k, v in schet.items() if v}


# ---------- команда ----------

NAZVANIYA = {"avtor": "автор", "data": "дата", "tekst": "текст"}


def spisok(slovar):
    return ", ".join(f"{k}: {v}" for k, v in slovar.items()) if slovar else "нет"


def pechat_info(put, args):
    fmt = args.format or opredelit_format(put)
    stroki = [f"Файл: {os.path.basename(put)}", f"Формат: {fmt}"]
    kolonki = None
    if fmt == "csv":
        info = info_csv(put)
        podskazka = ", ".join(f"{NAZVANIYA[k]} → «{v}»" for k, v in info["podskazka"].items())
        stroki += [
            f"Кодировка: {info['kodirovka']}, разделитель: «{info['razdelitel']}», строк: {info['strok']}",
            "Колонки: " + ", ".join(f"«{k}»" for k in info["kolonki"]),
            "Подсказка, где что: " + (podskazka or "не угадал"),
            "Первые строки (телефоны и почты скрыты):",
        ]
        stroki += ["  " + " | ".join(s) for s in info["primer_strok"]]
        if args.avtor and args.data and args.tekst:
            kolonki = {"avtor": args.avtor, "data": args.data, "tekst": args.tekst}
        elif len(info["podskazka"]) == 3:
            kolonki = info["podskazka"]
            stroki.append("Участники ниже посчитаны по подсказке: проверьте колонки.")
        if not kolonki:
            print("\n".join(stroki))
            return
    soobshcheniya, stat = prochitat(put, fmt, kolonki)
    schet = Counter(s["avtor"] for s in soobshcheniya)
    daty = sorted(s["data"] for s in soobshcheniya if s["data"][:2] == "20")
    stroki.append("Участники (сообщений с текстом):")
    stroki += [f"  {avtor}: {n}" for avtor, n in schet.most_common()]
    if daty:
        stroki.append(f"Период: {daty[0][:10]} — {daty[-1][:10]}")
    stroki.append("Пропущено без текста: " + spisok(stat["propushcheno"]))
    stroki.append(f"Служебных сообщений: {stat['sluzhebnyh']}")
    print("\n".join(stroki))


def razobrat(put, args):
    kolonki = None
    if args.avtor or args.data or args.tekst:
        kolonki = {"avtor": args.avtor, "data": args.data, "tekst": args.tekst}
    soobshcheniya, stat = prochitat(put, args.format, kolonki)
    if args.s:
        soobshcheniya = [s for s in soobshcheniya if s["data"][:2] != "20" or s["data"] >= args.s]
    if not soobshcheniya:
        raise OshibkaRazbora("В выгрузке нет сообщений с текстом" + (f" начиная с {args.s}" if args.s else "") + ".")
    razmecheno, skryto = razmetit(soobshcheniya, args.vladelec or [])
    roli = Counter("Владелец" if s["rol"] == "Владелец" else "клиенты" for s in razmecheno)
    klientov = len({s["rol"] for s in razmecheno if s["rol"] != "Владелец"})
    daty = sorted(s["data"] for s in razmecheno if s["data"][:2] == "20")
    period = f"{daty[0][:10]} — {daty[-1][:10]}" if daty else "не определён"
    svodka = [
        "# Переписка для разбора, подготовлена скриптом razobrat.py",
        f"# Формат: {stat['format']}. Период: {period}.",
        f"# Сообщений с текстом: {len(razmecheno)} (владелец {roli['Владелец']}, клиенты {roli['клиенты']}). "
        f"Клиентов: {klientov}.",
        "# Скрыто: " + spisok(skryto),
        "# Пропущено без текста: " + spisok(stat["propushcheno"]),
        f"# Служебных сообщений: {stat['sluzhebnyh']}",
    ]
    dialog = [f"{s['data']} | {s['rol']} | {s['tekst'].replace(chr(10), ' / ')}" for s in razmecheno]
    if args.o:
        with open(args.o, "w", encoding="utf-8") as f:
            f.write("\n".join(svodka + [""] + dialog) + "\n")
        print("\n".join(svodka + [f"# Записано в {args.o}"]))
    else:
        print("\n".join(svodka + [""] + dialog))


def main(argv=None):
    for potok in (sys.stdout, sys.stderr):
        if hasattr(potok, "reconfigure"):
            potok.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Готовит выгрузку переписки к разбору.")
    p.add_argument("put", help="файл выгрузки: result.json, .txt WhatsApp или .csv")
    p.add_argument("--info", action="store_true", help="показать формат, участников, колонки CSV")
    p.add_argument("--vladelec", action="append", help="имя владельца как в выгрузке; можно несколько раз")
    p.add_argument("--avtor", help="CSV: колонка с автором")
    p.add_argument("--data", help="CSV: колонка с датой")
    p.add_argument("--tekst", help="CSV: колонка с текстом")
    p.add_argument("--s", help="брать сообщения начиная с даты ГГГГ-ММ-ДД")
    p.add_argument("--format", choices=["telegram", "whatsapp", "csv"], help="если формат не угадался")
    p.add_argument("-o", help="записать результат в файл")
    args = p.parse_args(argv)
    try:
        if args.info:
            pechat_info(args.put, args)
        else:
            razobrat(args.put, args)
    except OshibkaRazbora as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"Ошибка: файл не читается как выгрузка ({e}).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
