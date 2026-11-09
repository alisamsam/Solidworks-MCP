# SolidWorks MCP — uporabniški vodič

Stanje kataloga: **2026-10-19; 249 registriranih orodij v 13 skupinah**.
To je vodič za naročanje dela v slovenščini. Ni ti treba poznati imen ukazov,
pisati JSON ali naštevati vrstnega reda API klicev.

## Najkrajša uporabna zahteva

> Na naši kopiji [projekt/kos] naredi [spremembo] z merami [mere]. Pred posegom
> preveri pravi kos in reference, po njem preveri geometrijo ter pokaži rezultat.
> Izvirnikov ne spreminjaj.

Če kos ni jasen, najprej naroči **»Pripravi označen pregled tega kosa za odločitev.«**
Agent pridobi točno komponento, pripravi primeren prikaz in po potrebi vpraša.
Namesto dolgega imena lahko uporabljaš oznako iz dogovorjenega prikaza.

## Kaj lahko naročiš za svoje delo

| Želim | Primer naročila | Podrobnosti |
|---|---|---|
| Upognjena pločevina | Izdelaj pločevinasto polico 400 × 200 × 2 mm, z zavihoma 30 mm in radijem 2 mm. Najprej uskladi smer zavihov. | [Pločevina](tools-sheetmetal.md) |
| Več pločevin v enem partu | V isti part dodaj še drugo ločeno pločevinasto telo debeline 3 mm. Obstoječega ne spreminjaj. | [Pločevina](tools-sheetmetal.md) |
| Varjenec | Iz črt te skice naredi več členov v enem weldment partu. Najprej preveri našo knjižnico profilov. | [Varjenci](tools-weldments.md) |
| Stiki in ojačitve | Preveri stik teh dveh profilov; nato pripravi dogovorjeno obrezavo, pokrov ali ojačitev. | [Varjenci](tools-weldments.md) |
| Luknje | Na tej ploskvi naredi dogovorjene izvrtine po DIN ali ISO. Najprej pokaži razpoložljive velikosti. | [Modeliranje](tools-features.md) |
| Robovi za odločitev | Za T09 pripravi vse robove za odločitev v označenih pogledih. Modela še ne spreminjaj. | [Izbira kosov](tools-assembly.md) |
| Zaokrožitve/posnetja | Na dogovorjenih robovih tega parta naredi R2 oziroma posnetje 1 × 45°. Pred izvedbo preveri izbor. | [Modeliranje](tools-features.md) |
| Sestavljanje | V naši kopiji vstavi ta kos, preveri položaj in ga zveži z dogovorjenima ploskvama. | [Sestavi](tools-assembly.md) |
| Vijaki iz knjižnice | Pokaži razpoložljive vijake ISO 4017 M10 in nato vstavi izbrano dolžino. | [Knjižnica](tools-assembly.md) |
| Razrezni seznam | Osveži razrez varjenca in pokaži, katera telesa pripadajo vsaki postavki. | [Varjenci](tools-weldments.md) |
| Posamezni kosi iz teles | Iz teh teles naše čiste kopije pripravi povezane parte in sestav. Predhodno preveri izhodne poti. | [Save Bodies](tools-weldments.md) |
| DXF | Preveri razvitje tega kosa in ga izvozi v novo DXF datoteko za razrez. | [Pločevina](tools-sheetmetal.md) |
| DXF izbranega telesa | Iz tega večtelesnega parta izvozi samo dogovorjeno pločevino v DXF. Izvornega modela ne spreminjaj. | [Pločevina](tools-sheetmetal.md) |
| Tehnična risba | V pripravljeno risbo dodaj standardne poglede, ustrezne mere in razrezno tabelo. | [Risbe](tools-drawing.md) |
| Varna sprememba projekta | Naredi neodvisno kopijo projekta z vsemi referencami in delaj samo v njej. | [Kopije](tools-project.md) |
| Trki | Na naši kopiji preveri volumenske trke in naštej udeležene komponente. | [Pregled sestava](tools-project.md) |
| Koncept stopnic/ograje | Iz teh potrjenih mer pripravi koncept in posebej naštej manjkajoče podatke. | [Koncepti](tools-planners.md) |
| Nosilnost | Pripravi dogovorjeno študijo z navedenim materialom, vpetjem in obremenitvijo ter pokaži reakcije in pomike. | [Simulacije](tools-simulation.md) |

To so vzorci naročil, ne obljuba ene samodejne operacije za poljubno geometrijo.
Agent izbere dejansko omogočena orodja in preveri njihove podprte načine.

## Tri stvari, ki preprečijo nesporazume

1. **Pravi kos.** Povej projekt/revizijo in po potrebi pokaži mesto na sliki.
   Enako ime ne zagotavlja istega primerka. Pred spremembo se referenca preveri.
2. **Želeni rezultat.** Navedi mero in enoto ter stran/smer, kadar vpliva na kos.
   Pri predlogu s puščico ločimo obstoječi obris od želene spremembe.
3. **Kaj shraniti.** Povej, ali želiš samo pregled, spremembo naše kopije ali
   shranjen izhod. Tvojih neshranjenih sprememb nikoli ne zavržemo brez potrditve.

## Kaj trenutno ne smemo zamenjevati

- SVG za dogovor ni DXF za izdelavo. Trenutni SVG kaže en kos in uporablja
  oznake iste MCP seje; po restartu/spremembi modela pripravimo svež prikaz.
- Izbor roba komponente še ne omogoča poljubnega urejanja parta znotraj sestava.
- Več pločevinastih teles je podprtih; s tem še ni potrjen samodejen DXF vseh teles.
- Kozmetični zvar je oznaka/dolžina, ne dodan material ali nosilnost zvara.
- Razrezni seznam ni optimizacija nabavnih palic. Merjena geometrija ni sama
  po sebi obračunska ali nabavna količina.
- Uspešen izračun simulacije še ne potrdi pravilnih materialov, vpetij ali mreže.
- Routing/SN4: priključke in geometrijo beremo/urejamo v omejenem obsegu;
  prava samodejno generirana SN4 cev/trasa še ni dokončana. Razvoj je odložen.

## Celoten seznam po področjih

- [Pločevina](tools-sheetmetal.md)
- [Varjenci in razrez](tools-weldments.md)
- [Sestavi, knjižnica in izbira kosov](tools-assembly.md)
- [Projektne kopije in spremembe](tools-project.md)
- [Dokumenti, pregled, meritve in izvozi](tools-core.md)
- [Volumensko modeliranje](tools-features.md)
- [Risanje skic](tools-sketch.md)
- [Urejanje in določanje skic](tools-sketch_edit.md)
- [Tehnične risbe](tools-drawing.md)
- [Površine](tools-surfaces.md)
- [Konceptni izračuni](tools-planners.md)
- [Simulacije](tools-simulation.md)
- [Routing — odloženo področje](tools-routing.md)

V katalogu ima vsako orodje primer naročila, učinek, mejo in oznako zapisane
preverjenosti. Ta vodič ne izvaja CAD in ni nov preizkus vseh opisanih poti.
