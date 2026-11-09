# 26 API & Automation — navodila za obdelavo

## Opomba — izključeni moduli

**PDM API in 3DEXPERIENCE API nista predmet obravnave.** Obravnavaj samo SOLIDWORKS Core API.

## Kaj poudariti

- **SOLIDWORKS API** — programski vmesnik za SOLIDWORKS (COM-based, VBA, .NET)
- **VBA Macros** — makroji v VBA (Visual Basic for Applications), vgrajeni v SW
- **Macro Recorder** — samodejni zajem korakov kot VBA koda
- **Document Object Model (DOM)** — hierarhija objektov v SW API (ISldWorks → IModelDoc2 → IFeature...)
- **Part Automation** — avtomatizacija kreacije partov (sketchi, featurji, lastnosti)
- **Assembly Automation** — vstavljanje komponent, dodajanje matov programsko
- **Drawing Automation** — kreacija risb, pogledov, mer programsko
- **Custom Properties Automation** — branje in pisanje custom properties
- **Export Automation** — samodejni izvoz v PDF, DXF, STEP iz SW
- **Batch Processing** — obdelava množice datotek (npr. masovni izvoz vseh partov v PDF)
- **Task Scheduler** — SW vgrajen planer nalog (rebuild, export, print)
- **.NET Add-ins** — naprednejši add-ini v C# ali VB.NET
- **UI Customization** — dodajanje menijev, toolbarjev, PropertyManagerjev prek API
- **Error Handling** — obvladovanje napak v makrojih (On Error, Try/Catch)
- **Logging** — zapisovanje logov za sledljivost avtomatiziranih procesov
- **Excel povezava** — branje/pisanje Excel datotek iz makroja (ADODB, Interop)
- **ERP izvoz brez PDM** — CSV, Excel ali XML izvoz BOM podatkov za ERP

## Obvezne usmeritve

- Pri **makrojih** razloži varnost in vzdrževanje:
  - Makro brez dokumentacije je neobvladljiv po 6 mesecih
  - Vsakemu makroju dodaj: namen, avtor, datum, parametri, primer klica
  - Makro brez error handlinga pusti SW v nedefinirani stanje pri napaki
- Pri **Macro Recorder** razloži omejitve posnete kode:
  - Posneta koda je linearna, brez parametrov in pogojev
  - Deluje samo za točno isti model, na katerem je bila posneta
  - Vredna kot učni pripomoček in izhodišče — ne kot končna rešitev
- Pri **automation export** razloži tipičen PDF, DXF, STEP workflow:
  - Odpri Part/Assembly/Drawing → nastavi export opcije → SaveAs / SaveToFile
  - Primer: masovni DXF izvoz vseh flat patterov iz mape
- Pri **error handling** razloži pomen logiranja:
  - Brez loga pri napaki ne veš, katera datoteka je bila problematična
  - Minimalni log: ime datoteke, timestamp, opis napake
- Pri **ERP povezavi** jasno navedi:
  - To je osnoven izvoz (CSV, Excel) brez PDM
  - Ne nadomesti PDM/ERP integracije s polnim PDM — je ročni ali skriptni izvoz
  - PDM API (ki je izključen) bi dal boljšo integracijo

## Tipični primeri podtem

- Osnove SOLIDWORKS API (DOM, objektni model)
- Makro snemanje in urejanje
- VBA osnove za SOLIDWORKS
- Part, Assembly, Drawing avtomatizacija
- Custom Properties branje/pisanje
- PDF, DXF, STEP batch export
- BOM izvoz v Excel/CSV za ERP
- Task Scheduler
- .NET Add-in osnove
- Error Handling in Logging
- Excel ↔ SOLIDWORKS integracija
