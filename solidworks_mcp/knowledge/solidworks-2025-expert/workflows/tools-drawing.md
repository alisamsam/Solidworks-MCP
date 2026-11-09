# Tehnične risbe — uporabniški primeri

Stanje: 2026-10-19; 7 registriranih orodij.

[Začetni vodič](tools.md)

## Kako brati seznam

Vsaka vrstica poda primer, ki ga lahko napišeš agentu. To ni neposredni MCP/JSON
klic: agent pred izvedbo dopolni natančne mere, reference, datoteke in konfiguracijo.
Če jih ne more zanesljivo ugotoviti, vpraša. Zapis orodja je namenjen iskanju in
sledljivosti; imen si ni treba zapomniti.

**Učinek** je razred operacije iz registracije. »Pregled« ni splošno jamstvo, da
native API nikoli ne osveži podatkov (npr. razrezni seznam); glej mejo v vrstici.
Izvoz naredi datoteko, projektni poseg pa lahko vpliva na projektne reference.
Shranjevanje in zapiranje sta vedno izrecna dela naloge.

**Dokazi** pomenijo zgodovinske vpise iz registra zahtev:

- **P**: obstaja vpis o native/MCP preverjanju določene zahteve; ne vseh načinov orodja.
- **T**: v registru so samo enotski testi, brez potrjenega native preizkusa te zahteve.
- **O**: v registru obstaja neuspešen preizkus; preberi njegovo mejo in raje uporabi alternativo.
- **M**: mešani uspešni in neuspešni zapisi; potreben je pregled konkretnega primera.
- **—**: ni ločene povezane postavke v registru; to samo po sebi ne pomeni, da orodje ne deluje.

Registrirano ni isto kot trenutno omogočeno. Trenutni profil, zaščiteni način in
nameščeni dodatki lahko orodja skrijejo ali blokirajo; za trenutno stanje vprašaj
»Katera orodja so zdaj na voljo?«. Routing ostaja odložen in privzeto skrit.

| Orodje | Kaj mu naročiš | Učinek | Meja / potrebni podatki | Dokazi |
|---|---|---|---|---|
| `add_drawing_dimension` | Na tem risalnem pogledu samodejno dodaj osnovne mere. | sprememba modela | Samodejno baseline kotiranje celega izbranega pogleda, ne ročna postavitev izbrane mere. | P |
| `add_standard_3_view` | Na risbo dodaj tri standardne poglede tega modela. | sprememba modela | Predhodno pripravljen dokument tehnične risbe. | P |
| `auto_balloon` | Na risalnem pogledu označi kose z balončki. | sprememba modela | Zahteva ustrezne podatke BOM/cut-list; ni SVG vezava robov. | — |
| `create_documentation_drawing` | Za ta kos ali sestav naredi prvokotno risbo s tremi pogledi ter shrani native risbo in PDF. | projektni poseg | Nova izolirana kopija in nova mapa; osnutek z oznako NI ZA IZDELAVO, brez potrjene celovitosti mer, tolerance, BOM ali montažnih navodil. | P |
| `insert_cut_list_table` | Na risbo vstavi razrezno tabelo varjenca. | sprememba modela | Potreben ustrezen model/pogled in predloga tabele. | P |
| `insert_marked_dimensions` | Na ta pogled prenesi modelne mere, označene za risbo. | sprememba modela | Ne uvozi samodejno vseh neoznačenih mer. | P |
| `list_drawing_views` | Pokaži poglede na aktivnem listu risbe. | pregled | Zahteva tehnično risbo, ne aktivnega parta. | — |
