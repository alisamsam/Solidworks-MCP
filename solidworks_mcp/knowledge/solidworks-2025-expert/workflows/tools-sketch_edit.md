# Urejanje in določanje skic — uporabniški primeri

Stanje: 2026-10-19; 16 registriranih orodij.

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
| `add_sketch_dimension` | Ta segment skice določi z mero 100 mm. | sprememba modela | Referenčne/driven mere ni mogoče uporabljati kot gonilno mero. | P |
| `add_sketch_relation` | Med tema segmentoma dodaj vzporednost, sovpadnost ali drug podprt odnos. | sprememba modela | Obstoječi odnos ni nova uspešno dodana vez. | P |
| `delete_sketch_relations` | Iz te skice odstrani vse odnose izbrane vrste. | sprememba modela | To spremeni določljivost geometrije. | P |
| `extend_entities` | Te skicne segmente podaljšaj do določenega stika. | sprememba modela | Podprte native vrste segmentov in pravilna skica. | — |
| `get_sketch_relations` | Pokaži odnose skice in ali je povsem določena. | pregled | Brez dodajanja ali brisanja odnosov. | P |
| `offset_entities` | Te skicne segmente odmakni za 5 mm na dogovorjeno stran. | sprememba modela | Smer odmika mora biti jasna. | P |
| `rotate_entities` | To skico zasukaj okoli navedene točke za 30 stopinj. | sprememba modela | Native operacija lahko zavrti tudi koordinatni okvir skice. | P |
| `scale_entities` | Te segmente povečaj za navedeni faktor. | sprememba modela | Skaliranje je okoli izhodišča skice. | P |
| `sketch_chamfer` | Vogal te skice posnemi z navedenima merama. | sprememba modela | To ni posnetje robov 3D telesa. | P |
| `sketch_fillet` | Vogal te skice zaokroži z navedenim radijem. | sprememba modela | To ni zaokrožitev robov 3D telesa. | P |
| `sketch_mirror` | Te segmente zrcali čez navedeno središčnico. | sprememba modela | Zrcalna črta naj bo neodvisna od zrcaljenih segmentov. | P |
| `sketch_pattern_circular` | Te skicne segmente enakomerno ponovi okoli središča. | sprememba modela | Določi število in skupni kot; native središče se preveri. | P |
| `sketch_pattern_linear` | Te skicne segmente ponovi v mreži 2 × 3. | sprememba modela | Število vključuje začetni primerek. | P |
| `split_entities` | Ta skicni segment razdeli pri navedeni točki. | sprememba modela | Zaprta krivulja zahteva dve točki delitve. | P |
| `toggle_construction` | Te črte spremeni v konstrukcijske oziroma navadne. | sprememba modela | Navedi želeno stanje, da ne obračamo na slepo. | P |
| `trim_entities` | Odreži odvečni del teh skicnih segmentov. | sprememba modela | Najprej določimo točna imena segmentov in mesto reza. | P |
