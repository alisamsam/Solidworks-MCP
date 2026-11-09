# Pločevina — uporabniški primeri

Stanje: 2026-10-19; 11 registriranih orodij.

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
| `create_edge_flange` | Na tem ravnem robu dodaj 30 mm zavih s kotom 90 stopinj. | sprememba modela | Rob mora pripadati pločevini; dolžina, kot in smer morajo biti določeni. | P |
| `create_miter_flange` | Na ta rob dodaj profilni zavih po pripravljeni skici. | sprememba modela | Preverjen omejen odprt profil s štirimi segmenti; ne poljubna skica. | P |
| `create_sheet_metal_base_flange` | Iz te skice naredi pločevino debeline 2 mm z radijem 2 mm. | sprememba modela | Z new_body lahko doda ločeno telo z lastnimi parametri v isti part. | P |
| `create_sheet_metal_hem` | Na izbranem robu naredi odprt ali zaprt povratni zavih. | sprememba modela | Trenutno enotelesna upognjena pločevina in raven rob. | P |
| `create_tab_and_slot` | Med tema telesoma pripravi povezavo z jezičkom in režo. | sprememba modela | Točen rob prvega telesa in ploskev drugega; ne potrdi nosilnosti spoja. | P |
| `export_flat_pattern` | Izvozi razvitje tega pločevinastega kosa v DXF. | izhodna datoteka | Neposredni izvoz; za izbrano telo in izolacijo vira uporabi export_sheet_metal_body_dxf. | P |
| `export_sheet_metal_body_dxf` | Iz tega večtelesnega parta izvozi samo izbrano pločevinasto telo v DXF za razrez. | izhodna datoteka | Čista shranjena kopija, svež indeks in stamp; izvozi prek ločene kopije v novo mapo zunaj projekta. Brez batch/nestinga. | P |
| `flatten_sheet_metal` | Razvij oziroma ponovno upogni ta pločevinasti kos. | sprememba modela | Začasno spremeni stanje modela; večtelesni izvoz ostaja omejen. | — |
| `get_flat_pattern_info` | Izmeri gabarit razvitja in kos vrni v upognjeno stanje. | izbor/pogled/stanje | Med branjem dejansko razvije in ponovno upogne model. | — |
| `get_sheet_metal_info` | Preberi osnovno debelino, radij in K-faktor pločevine. | pregled | Samo prva definicija; za več teles list_sheet_metal_bodies. | — |
| `list_sheet_metal_bodies` | Za vsako pločevinasto telo pokaži debelino, radij in stanje razvitja. | pregled | Vključi skrita telesa; stanje ni dokaz pravilnega DXF za vsako telo. | P |
