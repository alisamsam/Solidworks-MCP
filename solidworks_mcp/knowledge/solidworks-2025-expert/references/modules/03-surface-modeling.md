# 03 Surface Modeling — navodila za obdelavo

## Vloga in obseg modula

Surface Modeling je napredna tehnika za ustvarjanje geometrij, ki jih z standardnim solid modeliranjem ni mogoče doseči ali pa jih je težko doseči. Površine so matematično "odprte lupine" brez debeline — dokler jih ne zapremo in pretvorimo v solid. Površinsko modeliranje se v industriji uporablja za tri namene: kompleksne organske oblike (avtomobilska karoserija, potrošna elektronika), popravilo uvožene geometrije ter hibridno modeliranje (kombinacija solid + surface orodij).

**Predpogoj**: Surface Modeling zahteva solidno znanje Part Modelinga (modul 02). Brez razumevanja featurejev, skic in reference managementa je surface delo neproduktivno.

---

## Kaj poudariti

### Solid vs. Surface — temeljna razlika

| Lastnost | Solid Body | Surface Body |
|----------|-----------|-------------|
| Definicija | Zaprto telo z notranjo in zunanjo stranjo | Odprta lupina brez debeline |
| Masa | Ima maso in prostornino | Nima mase |
| FEA | Polno podprto | Omejeno (Shell elements) |
| Vidnost v FeatureManager | Bodies > Solid Bodies | Bodies > Surface Bodies |
| Barva v modelu | Solida | Prozorna ali barvna (po nastavitvi) |
| Za proizvodnjo | Neposredno za CAM, simulacijo | Najprej pretvoriti v solid (Thicken ali Knit) |

**Kdaj surface ni primerna alternativa solid:**
- Za standardne prizmatične kose → Solid je vedno hitrejši in stabilnejši
- Ko ni potrebe po G1/G2 kontinuiteti → Solid Fillet zadostuje
- Ko ni uvožene geometrije za popravilo

**Kdaj surface je prava tehnika:**
- Organske oblike brez jasnih parametričnih pravil (prostih krivulj oblik)
- Karoserija, čelada, ergonomska ohišja, dizajnerski kosi
- Popravilo uvožene geometrije (STEP, IGES) z manjkajočimi ali napačnimi površinami
- Hibridni modeli: solid osnova + surface za kompleksni detail

---

### Osnovi surface featurji

**Extruded Surface / Revolved Surface / Swept Surface / Lofted Surface:**
- Enaka logika kot Boss featurji v solid modeliranju
- Rezultat je odprta površina (ne solid)
- Razlika: ne "zapolnijo" prostora — samo definirajo lupino

**Planar Surface:**
- Ustvari ravno površino iz zaprt