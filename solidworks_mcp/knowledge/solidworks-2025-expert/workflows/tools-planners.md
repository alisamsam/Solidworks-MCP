# Konceptni izračuni — uporabniški primeri

Stanje: 2026-10-19; 5 registriranih orodij.

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
| `plan_railing` | Izračunaj razpored stebrov ograje za navedeno dolžino in višino. | pregled | Brez konstrukcijskega izračuna nosilnosti. | — |
| `plan_segments` | Predlagaj delitev dolžin po naših transportnih in cinkarskih omejitvah. | pregled | Omejitve poda uporabnik; orodje ne izumi spojev. | — |
| `plan_stair` | Iz dogovorjene višine in števila dvigov pripravi koncept stopnic. | pregled | Konceptni izračun; ne ustvari CAD in ne potrdi skladnosti. | — |
| `plan_stair_turn` | Izračunaj koncept podesta ali enakokotnih zavitih stopnic. | pregled | Koncept, ne preverjena geometrija vsake dejanske stopnice. | — |
| `review_galvanizing` | Preglej navedene votline in predvideni položaj pri cinkanju. | pregled | Ne dodaja samodejno odzračevalnih lukenj. | — |
