# The distributor demo (Anadolu Dağıtım)

A second model in the same app: a fictional Turkish FMCG distributor on **Postgres** (the first model is AdventureWorks on StarRocks). The data is live: a simulator adds orders, payments and returns every 15 minutes, so the numbers change while you look.

## Start it
Put these in `.env` (`openssl rand -hex 16` for the password):

```
DISTRIBUTOR_DB_PASSWORD=...
MODELS=adventureworks,distributor        # which models the pages, builder, lab and admin serve: the header's model switch appears when there are two
```

(The default is `MODELS=adventureworks`: starting the `distributor` profile alone does not show the switch.) On a stack that already has data, run `postgres/sync-access.sh` (the access tables for the row rules) and `keycloak/sync-users.sh` (the demo users) once, then `psql -f models/distributor/rules.sql` against the access database for their rules. Then either

```bash
# next to the AdventureWorks stack (both models, one switch)
docker compose --profile starrocks --profile distributor up -d --build
# or alone, without StarRocks: see models/distributor/README.md
```

The first start writes three years of history (about a minute); Cube starts when it is in. Sign in as `admin` (`TEST_USER_PASSWORD`).

## Walk-through (English)
1. **The switch.** In the header, *Model*: AdventureWorks or Anadolu Dağıtım. The choice is `?model=distributor` in the address and follows you to the list, the builder, the SQL lab and the admin console.
2. **Satış özeti** (sales summary): revenue, gross margin, orders and collections with the year-on-year change; click a segment or a region to filter the page.
3. **Tahsilat ve vade** (collections and due dates): the aging of open invoices (not due, 1-30, 31-60, 61-90, 90+ days) and the dealers with the largest overdue balance. This moves as payments arrive.
4. **Stok durumu** (stock): today's stock value, items below their reorder point and out of stock, days of cover.
5. **Build one.** In the builder ask: *ciro ve tahsilat aylık, bayi ve bölge, tablo* (or in English *revenue and collected by month, by dealer and region, a table*). The rule-based stand-in understands the model's own Turkish words (`models/distributor/model.config.yml`); with a language-model key it writes any dashboard.
6. **SQL lab.** Switch the model, open the lab: the schema shows the distributor's cubes and an example; `select region, measure(revenue) from dealers ...` runs on the Cube SQL API under the same rules.
7. **Row rules.** Sign in as `marmara_mudur` (sees only the Marmara dealers), `marmara_temsilci` or `ege_temsilci` (a sales representative sees only their own dealers). In the admin console, *Row rules* lists the two dimensions, *dealer regions* and *sales representative*.

## Anlatım (Türkçe)
1. **Model seçici.** Üst çubukta *Model*: AdventureWorks ya da Anadolu Dağıtım. Seçim adreste `?model=distributor` olarak kalır; liste, oluşturucu, SQL laboratuvarı ve yönetim konsolu da seçilen modelde açılır.
2. **Satış özeti**: ciro, brüt kâr, sipariş ve tahsilat, geçen yıla göre değişimle; bir bayi tipine ya da bölgeye tıklayınca sayfa süzülür.
3. **Tahsilat ve vade**: açık faturaların yaşlandırması (vadesi gelmemiş, 1-30, 31-60, 61-90, 90+ gün) ve en çok vadesi geçmiş bakiyesi olan bayiler. Tahsilatlar geldikçe değişir.
4. **Stok durumu**: bugünkü stok değeri, yeniden sipariş noktasının altındaki ve tükenmiş ürünler, kapsama günü.
5. **Kendin oluştur.** Oluşturucuya *ciro ve tahsilat aylık, bayi ve bölge, tablo* yaz. Kural tabanlı yedek, modelin Türkçe sözcüklerini (`ciro`, `tahsilat`, `bayi`, `bölge`, `iade`, `stok`, ...) anlar; dil modeli anahtarıyla her paneli yazabilir.
6. **SQL laboratuvarı.** Modeli değiştirin; şema bu modelin küplerini ve bir örnek sorguyu gösterir; sorgu Cube SQL API üzerinden aynı kurallarla çalışır.
7. **Satır kuralları.** `marmara_mudur` yalnızca Marmara bayilerini, `marmara_temsilci` ve `ege_temsilci` yalnızca kendi bayilerini görür. Yönetim konsolunda *Satır kuralları* iki boyutu listeler: bayi bölgeleri ve satış temsilcisi.

## What the data does
Weekdays are busier than weekends; Ramazan and the bayram weeks shift demand; prices follow inflation (a year-on-year comparison means something); the four dealer types (chain, wholesaler, café-restaurant-hotel, corner shop) differ in order size, discount and payment term; invoices fall due by the dealer's term and are paid with a late tail (some partly, some not at all); about 2.5 % of lines come back with a reason. Revenue is about 2.2 billion TRY in the last full year. The generator is seeded, so the same install gives the same history (apart from where "now" is).
