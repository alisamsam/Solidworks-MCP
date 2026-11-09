# Routing — odloženo področje — uporabniški primeri

Stanje: 2026-10-19; 18 registriranih orodij.

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
| `configure_routing_component` | Temu kosu nastavi Routing opis oziroma pravilo vključevanja priključkov. | sprememba modela | Ne spremeni poljubne klasifikacije in ne ustvari cevi. | P |
| `create_routing_connection_point` | Na tem krožnem robu pripravi native cevni priključek CPoint. | sprememba modela | Ne ustvari trase ali dokončane cevne povezave. | P |
| `enter_routing_edit` | Vstopi v urejanje izbrane native Routing trase. | sprememba modela | Odloženo področje; stanje je treba dejansko preveriti. | — |
| `exit_active_routing_edit` | Zapusti aktivno native urejanje trase. | sprememba modela | To še ni kontrolirano shranjevanje dokončane trase. | — |
| `get_component_connection_points` | Pokaži lokalni in sestavni položaj priključkov tega primerka. | pregled | Naložen kos s pravo konfiguracijo; brez samodejnega resolve. | P |
| `get_routing_component_metadata` | Preberi native Routing vrsto in opis komponente. | pregled | Metapodatki niso dokaz prilagodljive cevi. | P |
| `get_routing_file_locations` | Preberi trenutne poti in nastavitve Routing knjižnice. | pregled | Brez spreminjanja globalnih nastavitev. | P |
| `get_routing_library_article` | Preberi točen SN4 artikel iz naše obstoječe knjižnice. | pregled | Manjkajočih mer ne izmišljuje; katalog ni dokazana native trasa. | P |
| `get_routing_status` | Preveri, ali je Routing sploh omogočen in nameščen. | pregled | Odloženo področje; prisotnost datotek ne potrdi licence ali delovanja. | P |
| `inspect_routing_active_edit` | Preveri, ali je aktivno pravo native urejanje trase. | pregled | Ne vstopa samodejno v urejanje. | — |
| `inspect_routing_context` | Preveri native Routing stanje aktivnega sestava. | pregled | Manager ne dokazuje ustvarjene cevi. | P |
| `list_routing_connection_points` | Pokaži native CPoint priključke aktivnega kosa. | pregled | Lokalni mm; ne vključuje vseh RPoint ali primerkov sestava. | P |
| `list_routing_path_segments` | Preberi ravne odseke in loke native Routing 3D skice. | pregled | Lokalna geometrija; konstrukcijski segmenti niso del dolžine trase. | P |
| `list_routing_reference_edges` | Pokaži krožne robove, primerne za pripravo CPoint priključka. | pregled | Indeksi so vezani na trenutno geometrijo kosa. | P |
| `measure_routing_connection_gap` | Izmeri razmik in smerno poravnavo teh dveh priključkov. | pregled | Ujemanje ne potrdi fizične združljivosti ali povezane trase. | P |
| `resize_active_routing_line` | V pravilno aktivnem urejanju spremeni dolžino izbranega ravnega odseka. | sprememba modela | Ne dokazuje samodejno ustvarjene prilagodljive cevi. | — |
| `routing_properties_command` | Na naši Routing kopiji odpri oziroma potrdi podprte Route Properties. | sprememba modela | Native UI ovira ostaja; uspeh ne pomeni ustvarjene cevi SN4. | — |
| `update_routing_connection_point` | Temu CPoint spremeni premer, stub dolžino ali oznako priključka. | sprememba modela | Spremeni kos; napaka ne zagotavlja samodejne razveljavitve. | P |
