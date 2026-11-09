# 05 Drawings — navodila za obdelavo

## Vloga in obseg modula

Drawing dokumentacija je "uradni glas" modela. Risba (`.slddrw`) ni neodvisna — je projekcija modela in sestava. Vsaka sprememba modela se samodejno odraža v risbi ob rebuild. To je bistvena prednost SOLIDWORKS pred ročnim risanjem: dimenzije so vedno aktualne, ker izhajajo neposredno iz geometrije.

Ključni princip: **Risba ne definira modela — model definira risbo.**

---

## Kaj poudariti

### Osnove risalnega okolja

**Papirni formati (Sheet):**
- Desni klik na zavihek lista > Sheet Properties → nastavi format, orientacijo, merilo
- Sheet Format: predloga z rob okvirjem, opisno polje (title block), logotipom
- Ločite Sheet Format od Sheet: Sheet Format je "podlaga" (ozadje), Sheet je aktiven list

**Sheet Format urejanje:**
- Desni klik na Sheet > Edit Sheet Format → vstopite v urejevalno modo za title block
- Opomba: v Sheet Format modo ne morete dodajati Drawing Views!
- Izhod iz Sheet Format: Desni klik > Exit Sheet Format → vrnite se v normalen Drawing modo

**Multiple Sheets:**
- Desni klik na zavihek > Add Sheet → dodaj nov list (drugačen format, merilo)
- Koristno za: glavni pogledi na Sheet 1, detail/section views na Sheet 2, BOM na Sheet 3

---

### Drawing Views

**Model View:**
- Insert > Drawing View > Model → izberi Part ali Assembly
- SW pokaze okno z ortogonalnimi pogledi (Front, Top, Right, ...)
- Na prvem vnosu določi "parent view" — vsi nadaljnji so odvisni od njega

**Standard 3 View:**
- Insert > Drawing View > Standard 3 View → SW samodejno ustvari Front, Top, Right
- Hitrejša alternativa za standardne projekcije

**Projected View:**
- Click na obstoječ view, potem Insert > Drawing View > Projected → novi pogled je ortogonalna projekcija
- Potegni miško v smer projekcije (levo/desno/gor/dol) → SW doda ustrezen pogled

**Auxiliary View:**
- Projekcija pravokotna na nagnjeno površino ali rob
- Pogledi z oznako "A→" ali "B→"
- Koristno za: nagnjene ploščice, rebra, poševne stene

**Section View:**
- Insert > Drawing View > Section → nariši presečno linijo v obstoječem pogledu
- Aligned Section: presečna linija z "zlomom" — prikaže dva različna kuta preseka
- Half Section: razpolovni pr