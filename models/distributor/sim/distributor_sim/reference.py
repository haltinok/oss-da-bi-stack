"""The reference data: calendar, regions and provinces, reps, dealers and items. Built once, from a seed, so every run makes the same company."""
from __future__ import annotations

import datetime as dt
import random

from faker import Faker

MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

# Public holidays: the fixed ones, and the religious ones by year (the day before a bayram is a half day, which the calendar counts as a holiday too).
FIXED = {(1, 1): "Yılbaşı", (4, 23): "Ulusal Egemenlik ve Çocuk Bayramı", (5, 1): "Emek ve Dayanışma Günü", (5, 19): "Atatürk'ü Anma, Gençlik ve Spor Bayramı",
         (7, 15): "Demokrasi ve Millî Birlik Günü", (8, 30): "Zafer Bayramı", (10, 29): "Cumhuriyet Bayramı"}
RAMAZAN_BAYRAMI = {2023: (4, 21), 2024: (4, 10), 2025: (3, 30), 2026: (3, 20), 2027: (3, 9), 2028: (2, 27), 2029: (2, 14), 2030: (2, 4)}        # first day; three days
KURBAN_BAYRAMI = {2023: (6, 28), 2024: (6, 16), 2025: (6, 6), 2026: (5, 27), 2027: (5, 16), 2028: (5, 5), 2029: (4, 24), 2030: (4, 14)}          # first day; four days
RAMAZAN_START = {2023: (3, 23), 2024: (3, 11), 2025: (3, 1), 2026: (2, 18), 2027: (2, 8), 2028: (1, 28), 2029: (1, 16), 2030: (1, 5)}            # the fasting month, until the bayram


def holidays(year: int) -> dict[dt.date, str]:
    out = {dt.date(year, m, d): name for (m, d), name in FIXED.items()}
    if year in RAMAZAN_BAYRAMI:
        m, d = RAMAZAN_BAYRAMI[year]
        first = dt.date(year, m, d)
        out |= {first + dt.timedelta(days=i): "Ramazan Bayramı" for i in range(-1, 3)}
    if year in KURBAN_BAYRAMI:
        m, d = KURBAN_BAYRAMI[year]
        first = dt.date(year, m, d)
        out |= {first + dt.timedelta(days=i): "Kurban Bayramı" for i in range(-1, 4)}
    return out


def ramazan(day: dt.date) -> bool:
    """Is `day` in the fasting month (the demand for food and drinks shifts)?"""
    if day.year not in RAMAZAN_START or day.year not in RAMAZAN_BAYRAMI:
        return False
    start = dt.date(day.year, *RAMAZAN_START[day.year])
    end = dt.date(day.year, *RAMAZAN_BAYRAMI[day.year])
    return start <= day < end


def bayram_soon(day: dt.date, days: int = 4) -> bool:
    """Is a bayram one to `days` days away (dealers stock up)?"""
    year = day.year
    for table in (RAMAZAN_BAYRAMI, KURBAN_BAYRAMI):
        for y in (year, year + 1):
            if y in table:
                first = dt.date(y, *table[y])
                if 0 < (first - day).days <= days:
                    return True
    return False


def calendar_rows(start: dt.date, end: dt.date) -> list[tuple]:
    rows, day = [], start
    holiday_names: dict[dt.date, str] = {}
    for y in range(start.year, end.year + 1):
        holiday_names |= holidays(y)
    while day <= end:
        iso = day.isocalendar()
        rows.append((int(day.strftime("%Y%m%d")), day, day.year, (day.month - 1) // 3 + 1, day.month, MONTHS[day.month - 1], day.year * 100 + day.month, iso[1], iso[2], WEEKDAYS[iso[2] - 1],
                     iso[2] >= 6, day in holiday_names, holiday_names.get(day, "")))
        day += dt.timedelta(days=1)
    return rows


# ---- regions and provinces (81 provinces in 7 regions; the dealers are spread by the region's weight)
REGIONS = {
    "Marmara": (["İstanbul", "Kocaeli", "Bursa", "Tekirdağ", "Balıkesir", "Sakarya", "Çanakkale", "Edirne", "Kırklareli", "Yalova", "Bilecik"], 5.0),
    "Ege": (["İzmir", "Manisa", "Aydın", "Denizli", "Muğla", "Afyonkarahisar", "Kütahya", "Uşak"], 2.4),
    "İç Anadolu": (["Ankara", "Konya", "Kayseri", "Eskişehir", "Sivas", "Yozgat", "Aksaray", "Niğde", "Nevşehir", "Kırıkkale", "Kırşehir", "Karaman", "Çankırı"], 2.6),
    "Akdeniz": (["Antalya", "Mersin", "Adana", "Hatay", "Isparta", "Burdur", "Osmaniye", "Kahramanmaraş"], 2.2),
    "Karadeniz": (["Samsun", "Trabzon", "Ordu", "Giresun", "Zonguldak", "Rize", "Tokat", "Çorum", "Amasya", "Düzce", "Bolu", "Sinop", "Kastamonu", "Artvin", "Bartın", "Karabük", "Bayburt", "Gümüşhane"], 1.5),
    "Doğu Anadolu": (["Erzurum", "Malatya", "Van", "Elazığ", "Ağrı", "Erzincan", "Kars", "Bingöl", "Muş", "Bitlis", "Hakkâri", "Iğdır", "Ardahan", "Tunceli"], 0.8),
    "Güneydoğu Anadolu": (["Gaziantep", "Diyarbakır", "Şanlıurfa", "Mardin", "Batman", "Adıyaman", "Siirt", "Şırnak", "Kilis"], 1.2),
}
REGION_SLUG = {"Marmara": "marmara", "Ege": "ege", "İç Anadolu": "ic_anadolu", "Akdeniz": "akdeniz", "Karadeniz": "karadeniz", "Doğu Anadolu": "dogu_anadolu", "Güneydoğu Anadolu": "guneydogu"}

SEGMENTS = {      # term (vade) days, credit multiple, orders' lines, units multiple in cases, base discount, on-time probability, payment methods
    "Zincir Market": dict(terms=(60, 90), lines=5.0, cases=(2, 6), discount=8.0, ontime=0.72, methods={"Havale/EFT": 0.8, "Çek": 0.2}),
    "Toptancı": dict(terms=(45, 60), lines=4.0, cases=(2, 5), discount=12.0, ontime=0.62, methods={"Havale/EFT": 0.5, "Çek": 0.3, "Senet": 0.2}),
    "Otel-Restoran-Kafe": dict(terms=(30, 30), lines=3.0, cases=(1, 4), discount=5.0, ontime=0.66, methods={"Havale/EFT": 0.5, "Kredi Kartı (POS)": 0.3, "Nakit": 0.2}),
    "Bakkal": dict(terms=(30, 45), lines=3.0, cases=(1, 3), discount=3.0, ontime=0.8, methods={"Nakit": 0.45, "Kredi Kartı (POS)": 0.3, "Havale/EFT": 0.25}),
}

KIND_WORDS = {"Zincir Market": ["Süpermarketler", "Marketler Zinciri", "Gıda Merkezi", "Hipermarket"], "Toptancı": ["Toptan Gıda", "Ticaret", "Dağıtım", "Gıda Pazarlama"],
              "Otel-Restoran-Kafe": ["Restoran", "Otel", "Kafe", "Catering", "Lokanta"], "Bakkal": ["Bakkaliye", "Market", "Büfe", "Şarküteri", "Mini Market"]}

# ---- items: (category, subcategory, products with their pack size and base price in TRY at 2023-01, case size, VAT)
CATALOG = [
    ("Gıda", "Makarna", [("Burgu Makarna", "500 g", 17, 20, 1), ("Spagetti", "500 g", 17, 20, 1), ("Kalem Makarna", "500 g", 17, 20, 1), ("Tel Şehriye", "500 g", 16, 20, 1)]),
    ("Gıda", "Bakliyat", [("Kırmızı Mercimek", "1 kg", 42, 12, 1), ("Kuru Fasulye", "1 kg", 55, 12, 1), ("Pirinç Baldo", "1 kg", 60, 12, 1), ("Nohut", "1 kg", 48, 12, 1), ("Bulgur", "1 kg", 30, 12, 1)]),
    ("Gıda", "Yağ", [("Ayçiçek Yağı", "1 L", 78, 12, 1), ("Ayçiçek Yağı", "5 L", 380, 4, 1), ("Zeytinyağı Sızma", "1 L", 210, 6, 10), ("Margarin", "250 g", 24, 24, 10)]),
    ("Gıda", "Konserve", [("Domates Salçası", "700 g", 52, 12, 10), ("Biber Salçası", "700 g", 58, 12, 10), ("Konserve Mısır", "400 g", 28, 24, 10), ("Konserve Nohut", "400 g", 24, 24, 10), ("Ton Balığı", "160 g", 70, 24, 10)]),
    ("Gıda", "Kahvaltılık", [("Beyaz Peynir", "500 g", 120, 8, 10), ("Zeytin Siyah", "500 g", 85, 12, 10), ("Çilek Reçeli", "380 g", 45, 12, 10), ("Fındık Kreması", "350 g", 75, 12, 10), ("Bal Çam", "460 g", 130, 12, 10)]),
    ("Gıda", "Un ve Şeker", [("Buğday Unu", "2 kg", 38, 10, 1), ("Toz Şeker", "1 kg", 36, 20, 10), ("Küp Şeker", "750 g", 40, 20, 10), ("Tuz", "750 g", 9, 24, 1)]),
    ("İçecek", "Su", [("Doğal Kaynak Suyu", "0,5 L", 5, 24, 10), ("Doğal Kaynak Suyu", "1,5 L", 9, 12, 10), ("Maden Suyu", "200 ml", 7, 24, 10), ("Damacana Su", "19 L", 55, 1, 10)]),
    ("İçecek", "Gazlı İçecek", [("Kola", "1 L", 28, 12, 20), ("Kola", "2,5 L", 52, 6, 20), ("Limonlu Gazoz", "1 L", 20, 12, 20), ("Portakallı Gazlı İçecek", "1 L", 22, 12, 20)]),
    ("İçecek", "Meyve Suyu", [("Vişne Nektarı", "1 L", 32, 12, 20), ("Şeftali Nektarı", "1 L", 32, 12, 20), ("Karışık Meyve Suyu", "200 ml", 9, 27, 20), ("Portakal Suyu", "1 L", 40, 12, 20)]),
    ("İçecek", "Çay ve Kahve", [("Siyah Çay", "1 kg", 150, 10, 10), ("Süzen Poşet Çay", "100'lü", 55, 24, 10), ("Türk Kahvesi", "100 g", 60, 24, 10), ("Hazır Kahve 3'ü 1 Arada", "18'li", 70, 12, 20)]),
    ("İçecek", "Enerji İçeceği", [("Enerji İçeceği", "250 ml", 24, 24, 20), ("Enerji İçeceği", "500 ml", 36, 24, 20), ("Soğuk Çay Şeftali", "1 L", 26, 12, 20)]),
    ("Atıştırmalık", "Bisküvi ve Kraker", [("Sade Bisküvi", "200 g", 22, 24, 10), ("Çikolatalı Bisküvi", "150 g", 26, 24, 10), ("Tuzlu Kraker", "90 g", 14, 30, 10), ("Gofret", "40 g", 8, 48, 10)]),
    ("Atıştırmalık", "Cips ve Kuruyemiş", [("Patates Cipsi", "100 g", 24, 24, 20), ("Mısır Cipsi", "90 g", 22, 24, 20), ("Fındık İçi", "200 g", 85, 12, 10), ("Çiğ Badem", "200 g", 80, 12, 10), ("Çekirdek", "300 g", 40, 20, 10)]),
    ("Atıştırmalık", "Şekerleme", [("Sert Şeker", "250 g", 38, 20, 20), ("Sakız", "5'li", 12, 60, 20), ("Çikolata Sütlü", "80 g", 30, 24, 20), ("Lokum", "350 g", 65, 12, 10)]),
    ("Temizlik", "Çamaşır", [("Toz Deterjan", "4 kg", 150, 4, 20), ("Sıvı Deterjan", "2,5 L", 140, 6, 20), ("Yumuşatıcı", "1,5 L", 60, 8, 20), ("Çamaşır Suyu", "2 L", 32, 8, 20)]),
    ("Temizlik", "Bulaşık", [("Bulaşık Deterjanı", "750 ml", 55, 12, 20), ("Bulaşık Makinesi Tableti", "30'lu", 175, 6, 20), ("Bulaşık Süngeri", "5'li", 22, 24, 20)]),
    ("Temizlik", "Yüzey", [("Yüzey Temizleyici", "1 L", 48, 12, 20), ("Cam Sil", "750 ml", 42, 12, 20), ("Banyo Temizleyici", "750 ml", 50, 12, 20), ("Çöp Torbası", "20'li", 26, 24, 20)]),
    ("Kişisel Bakım", "Saç ve Vücut", [("Şampuan", "500 ml", 85, 12, 20), ("Saç Kremi", "350 ml", 75, 12, 20), ("Duş Jeli", "500 ml", 70, 12, 20), ("Sıvı Sabun", "500 ml", 40, 12, 20)]),
    ("Kişisel Bakım", "Ağız Bakımı", [("Diş Macunu", "100 ml", 38, 24, 20), ("Diş Fırçası", "tekli", 28, 36, 20), ("Ağız Gargarası", "500 ml", 60, 12, 20)]),
    ("Kişisel Bakım", "Kâğıt", [("Tuvalet Kâğıdı", "24'lü", 180, 4, 20), ("Kâğıt Havlu", "6'lı", 110, 6, 20), ("Peçete", "100'lü", 18, 48, 20), ("Islak Mendil", "90'lı", 35, 24, 20)]),
]
BRANDS = {"Gıda": ["Anadolu Lezzet", "Çukurova Sofra", "Ege Bahçe", "Karadeniz Doğal", "Toros Gıda"], "İçecek": ["Tazelik", "Pınar Kaynak", "Boğaz", "Yaylak", "Serin"],
          "Atıştırmalık": ["Keyifli", "Çıtır", "Tatlı Köşe", "Lezzet Durağı"], "Temizlik": ["Pırıl", "Berrak", "Ferah Ev", "Temiz Adım"], "Kişisel Bakım": ["Nazlı", "Saf Bakım", "Yumuşak Dokunuş", "Ferah"]}


def build_reps(rng: random.Random, fake: Faker) -> list[dict]:
    """Two sales reps per region; the first of a region is `<region>_temsilci` (the demo user), the second `<region>_temsilci2`."""
    reps, key = [], 1
    for region, slug in REGION_SLUG.items():
        for n in (1, 2):
            reps.append({"rep_key": key, "rep_username": f"{slug}_temsilci" + ("" if n == 1 else "2"), "rep_name": f"{fake.first_name()} {fake.last_name()}", "region": region})
            key += 1
    return reps


def build_dealers(rng: random.Random, fake: Faker, reps: list[dict], count: int, today: dt.date, history_years: int) -> list[dict]:
    """About `count` dealers over the provinces, a few big chains and many small shops: `weight` is how often each one orders (a power curve)."""
    weights = [r[1] for r in REGIONS.values()]
    regions = rng.choices(list(REGIONS), weights=weights, k=count)
    order = sorted(range(count), key=lambda i: rng.random())
    ranks = {i: pos + 1 for pos, i in enumerate(order)}                         # rank 1 is the biggest dealer
    start = today - dt.timedelta(days=365 * history_years)
    dealers = []
    for i in range(count):
        rank = ranks[i]
        segment = "Zincir Market" if rank <= 12 else "Toptancı" if rank <= 50 else "Otel-Restoran-Kafe" if rng.random() < 0.28 else "Bakkal"
        region = regions[i]
        province = rng.choice(REGIONS[region][0])
        rep = rng.choice([r for r in reps if r["region"] == region])
        seg = SEGMENTS[segment]
        weight = (1.0 / rank ** 0.5) * 30
        opened = start - dt.timedelta(days=rng.randint(30, 2500)) if rng.random() < 0.8 else start + dt.timedelta(days=rng.randint(20, 365 * history_years - 120))
        name_base = fake.last_name() if segment != "Zincir Market" else rng.choice(["Anadolu", "Bereket", "Yıldız", "Doğan", "Güven", "Özkan", "Erdem", "Kardeşler"])
        dealers.append({"dealer_key": i + 1, "dealer_code": f"B{i + 1:04d}", "dealer_name": f"{name_base} {rng.choice(KIND_WORDS[segment])} ({province})", "region": region, "province": province, "segment": segment,
                        "rep_key": rep["rep_key"], "rep_username": rep["rep_username"], "credit_limit": round(weight * 120_000 / 100) * 100 + 20_000, "payment_term_days": rng.randint(*seg["terms"]),
                        "opened_date": opened, "is_active": True, "weight": weight})
    return dealers


def build_items(rng: random.Random) -> list[dict]:
    items, key = [], 1
    for category, sub, products in CATALOG:
        for name, pack, price, case, vat in products:
            brand = rng.choice(BRANDS[category])
            for variant in range(rng.choice([3, 4, 4, 5, 6])):               # a few brands of the same product: about 380 items in all
                b = brand if variant == 0 else rng.choice(BRANDS[category])
                factor = rng.uniform(0.85, 1.35)
                base = max(3.0, round(price * factor, 2))
                items.append({"item_key": key, "sku": f"SKU{key:04d}", "item_name": f"{b} {name} {pack}", "category": category, "subcategory": sub, "brand": b, "base_price": base,
                              "case_size": case, "vat_rate": float(vat), "cost_ratio": rng.uniform(0.74, 0.88), "popularity": rng.paretovariate(1.6)})
                key += 1
    total = sum(i["popularity"] for i in items)
    for i in items:
        i["popularity"] = i["popularity"] / total
    return items
