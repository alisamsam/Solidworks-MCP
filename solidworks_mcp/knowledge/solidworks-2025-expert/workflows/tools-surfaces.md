# Površine — uporabniški primeri

Stanje: 2026-10-19; 12 registriranih orodij.

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
| `cut_with_surface` | S to ravno površino odstrani dogovorjeno stran telesa. | sprememba modela | Določi stran reza; ne poljubna ukrivljena površina. | P |
| `extend_surface` | Ta rob površine linearno podaljšaj za navedeno dolžino. | sprememba modela | En rob površinskega telesa. | P |
| `extrude_surface` | To skico iztisni v odprto površino. | sprememba modela | Enosmerni površinski iztis. | P |
| `filled_surface` | To zaprto skicno mejo zapolni s površinskim obližem. | sprememba modela | Ne pomeni poljubnega popravljanja uvoženega telesa. | P |
| `knit_surface` | Te stikajoče se površine zašij v en površinski sklop. | sprememba modela | Stik mora biti geometrijsko ustrezen. | P |
| `loft_surface` | Med tema profiloma pripravi odprto prehodno površino. | sprememba modela | Dve urejeni skici. | P |
| `offset_surface` | Od te ravne površine naredi vzporedno površino na odmiku. | sprememba modela | Trenutni podprti obseg je raven list. | P |
| `planar_surface` | Iz zaprte skice naredi ravno površino. | sprememba modela | Površina še nima prostornine materiala. | P |
| `revolve_surface` | To odprto skico zavrti okoli ene konstrukcijske osi v površino. | sprememba modela | Skica mora vsebovati točno eno ustrezno os. | P |
| `ruled_surface` | Iz tega roba pripravi tangentno izpeljano površino. | sprememba modela | Podprt tangentni način. | P |
| `sweep_surface` | Ta profil potegni po poti kot odprto površino. | sprememba modela | Ločeni skici profila in poti. | P |
| `thicken_surface` | To površino odebeli na navedeno debelino. | sprememba modela | Ni isto kot native definicija pločevine. | P |
