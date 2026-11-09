# Dokumenti, pregled, meritve in izvozi — uporabniški primeri

Stanje: 2026-10-19; 31 registriranih orodij.

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
| `bind_active_document` | Za nadaljnje korake uporabi ta aktivni dokument in konfiguracijo. | seja programa | Preprečuje nenamerno delo na drugem aktivnem dokumentu. | — |
| `capture_view` | Pripravi sliko trenutnega modela. | izbor/pogled/stanje | Slika je lahko prazna ali prekrita; vsebino je treba pregledati. | P |
| `close_document` | Zapri naš testni dokument brez shranjevanja. | sprememba modela | Pri uporabnikovih spremembah zavrženje zahteva dovoljenje. | — |
| `close_saved_outputs` | Preveri in zapri naše shranjene, nespremenjene izhodne dokumente. | seja programa | Neshranjenih, spremenjenih in uporabnikovih dokumentov ne zapira. | — |
| `connect_solidworks` | Poveži se s SolidWorksom. | seja programa | Po potrebi zažene program. | P |
| `create_new_assembly` | Ustvari nov prazen sestav. | seja programa | Vstavljanje in vezi so naslednji ločeni koraki. | P |
| `create_new_part` | Ustvari nov prazen kos. | seja programa | Novo poskusno delo shranimo ločeno od knjižnice. | — |
| `execute_python` | Izvedi posebej pregledano Python diagnostiko SolidWorksa. | surova koda | Surova koda; v zaščitenem načinu ni na voljo. | — |
| `export_face_to_dxf` | Izvozi izbrano ravno ploskev v DXF za razrez. | izhodna datoteka | Aktivni part; ni splošen izvoz pogleda sestava. | P |
| `export_step` | Izvozi ta kos v novo datoteko STEP. | izhodna datoteka | Določi izhodno pot; izvoz ni native zgodovina modela. | P |
| `export_stl` | Izvozi ta kos v novo datoteko STL. | izhodna datoteka | Uporabi trenutne nastavitve mreženja SolidWorksa; ta klic kakovosti ne nastavlja. | P |
| `get_body_bounding_box` | Pokaži zunanje gabarite teles tega kosa. | pregled | Izbira vidnih ali vseh teles; gabarit ni razvita mera ali nabavna dolžina. | — |
| `get_capabilities` | Povej, katera orodja so trenutno omogočena in katera blokirana. | pregled | To je trenutna dostopnost, ne dokaz uspešnega modeliranja. | P |
| `get_document_info` | Povej, kateri dokument je trenutno aktiven. | pregled | Preverimo pred spreminjanjem. | — |
| `get_mass_properties` | Izračunaj prostornino, maso in težišče kosa. | pregled | Masa je odvisna od dejansko dodeljenega materiala/gostote. | P |
| `get_modeling_guide` | Pokaži navodila za delo s pločevino. | pregled | Brez povezave s CAD; vodič ne izvede modeliranja. | — |
| `get_solidworks_info` | Preveri različico SolidWorksa in stanje trenutne seje. | pregled | Podatki o seji so odvisni od povezave. | P |
| `inspect_document` | Preglej aktivni dokument, funkcije, sestavo, mere in reference. | pregled | Razdelki se izberejo glede na dokument; ni celovita potrditev izdelovalnosti. | P |
| `list_body_edges` | Pokaži robove telesa v tem kosu. | pregled | Za robove komponent sestava uporabimo list_component_edges. | P |
| `list_open_documents` | Pokaži vse trenutno odprte dokumente. | pregled | Ne odpira in ne zapira dokumentov. | — |
| `list_planar_faces` | Pokaži ravne ploskve kosa, njihove položaje in indekse. | pregled | Indekse osvežimo po spremembi modela. | — |
| `list_planes` | Pokaži obstoječe referenčne ravnine. | pregled | Uporabimo dejanska imena iz modela. | P |
| `measure_distance` | Izmeri razdaljo med tema dvema potrjenima ploskvama kosa. | pregled | Potrebna sta aktualna indeksa ploskev in enota; ne poljubna referenca sestava. | P |
| `open_document` | Odpri navedeno datoteko SolidWorks. | seja programa | Vedno navedi pravo pot in revizijo. | P |
| `redo` | Ponovi zadnji razveljavljeni korak. | sprememba modela | Odvisno od native zgodovine dokumenta. | P |
| `restart_solidworks` | Po moji potrditvi varno ponovno zaženi SolidWorks. | seja programa | Zahteva izrecno potrditev; zavrne nevarno odprte dokumente. | — |
| `save_document` | Shrani naš delovni kos kot novo native datoteko v output. | sprememba modela | Uporabnikovih izvirnikov brez dovoljenja ne prepisujemo. | P |
| `set_units` | Za mere uporabljaj milimetre. | seja programa | Agent še vedno preveri enote posameznega orodja. | P |
| `set_view` | Obrni prikaz v izometrijo oziroma pogled od zgoraj. | izbor/pogled/stanje | Spremeni pogled, ne geometrije. | P |
| `undo` | Razveljavi zadnji podprt korak v modelu. | sprememba modela | Ni zagotovljen transakcijski povratek več operacij. | P |
| `zoom_fit` | Prilagodi povečavo, da se model vidi v celoti. | izbor/pogled/stanje | Samo sprememba pogleda. | P |
