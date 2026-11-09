# Sestavi, knjižnica in izbira kosov — uporabniški primeri

Stanje: 2026-10-19; 29 registriranih orodij.

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
| `add_mate` | Med tema referencama dodaj kotno, vzporedno ali drugo podprto vez. | sprememba modela | Ne ugibamo referenc samo po imenu kosa. | — |
| `assembly_diff` | Primerjaj ta sestav s pričakovanim seznamom komponent in položajev. | pregled | Primerjava najvišje ravni; ni splošna geometrijska primerjava. | — |
| `create_component_pattern` | Ta kos v sestavu ponovi linearno ali okoli osi. | sprememba modela | Potrebni so seme, smer/os, število in razmik/kot. | — |
| `delete_mate` | Odstrani točno navedeno vez iz sestava. | sprememba modela | Predhodno preverimo ime in vrsto vezi. | — |
| `export_assembly_manufacturing_package` | Iz svežega načrta izberi nekaj glavnih stranic in samo zanje pripravi STEP ter osnutke risb PDF v urejen paket. | projektni poseg | Za item_ids je obvezen plan_fingerprint kot expected_plan_fingerprint; preverijo se vse shranjene odvisnosti. Nova izolirana kopija, izrecni formati. STEP je celoten part; risbe nimajo potrjenih vseh mer. Grezene stranice niso samodejni kandidati za DXF. Napake in izpuščeni cilji ostanejo v kazalu. | P |
| `export_component_edge_svg` | Pripravi označene poglede robov tega kosa za dogovor. | izhodna datoteka | En kos/stran; žični prikaz, trenutna seja; ni izdelovalni DXF. | P |
| `get_component` | Preglej položaj, zasuk in vezi tega konkretnega primerka. | pregled | Trenutno točen primerek najvišje ravni. | — |
| `get_standard_part_sizes` | Pokaži razpoložljive velikosti izbranega standardnega dela. | pregled | Loči že izdelane in šele pripravljive velikosti. | — |
| `insert_component` | V sestav vstavi izbrani kos na dogovorjeni položaj. | sprememba modela | Določi datoteko in položaj; ni avtomatičnega dodajanja vezi. | P |
| `insert_standard_part` | Vstavi vijak izbranega standarda, velikosti in dolžine. | sprememba modela | Točen standard/velikost; vstavljanje še ni pravilna montažna vez. | — |
| `list_component_edges` | Pokaži robove točno tega kosa v sestavu, tudi če se datoteka ponavlja. | pregled | Točna native pot; filtri in strani, brez avtomatičnega resolve. | P |
| `list_component_faces` | Pokaži ploskve tega kosa v sestavu, da izbereva pravo za vez. | pregled | Po premiku ali dodani vezi osvežimo indekse. | — |
| `list_components` | Pokaži, kateri kosi so v sestavu in od kod so naloženi. | pregled | Hitri način za orientacijo, podrobni za transformacije in stanja. | P |
| `list_mates` | Pokaži obstoječe vezi sestava. | pregled | To so konstrukcijske vezi, ne dokaz odsotnosti trkov. | — |
| `list_standard_parts` | Pokaži standardne vijake, matice ali druge dele iz naše knjižnice. | pregled | Bere ustvarjeni katalog, ne išče poljubnih artiklov po spletu. | — |
| `mate_coincident` | Poravnaj ti dve ploskvi s sovpadno vezjo. | sprememba modela | Potrebna sta točna primerka in indeksa ploskev. | P |
| `mate_concentric` | Poravnaj osi teh dveh cilindričnih ploskev. | sprememba modela | Koncentričnost sama ne določi aksialne lege. | P |
| `mate_distance` | Med tema ploskvama dodaj vez z navedeno razdaljo. | sprememba modela | Natančne ploskve in razdalja z enoto. | P |
| `pack_and_go` | Pripravi paket sestava z vsemi referencami. | izhodna datoteka | Native Pack and Go; za neodvisno testiranje raje preverjeni copy_project. | O |
| `remove_component` | Iz naše kopije odstrani ta primerek kosa. | sprememba modela | Odstrani tudi njegove vezi; zahteva preverjeno trenutno datoteko. | — |
| `rename_component` | Preimenuj ta primerek komponente. | sprememba modela | Ne preimenuje projektnih datotek na disku. | — |
| `request_manufacturing_package_stop` | Ustavi skupinski izvoz po koncu trenutnega kosa in zapri njegove testne kopije. | projektni poseg | Potrebuje mapo tekočega paketa. Ne prekine native klica in ne zapre SolidWorksa; deluje mimo zasedene COM niti. | P |
| `select_component_edges` | Iz prej prikazanega seznama izberi te robove in preveri lastnika. | izbor/pogled/stanje | Posnetek iste MCP seje; po spremembi se seznam osveži. | P |
| `select_component_svg_edges` | Na tem prikazu T09 izberi R7 in R13 ter preveri prava robova. | izbor/pogled/stanje | Prikaz/map_id skupaj z oznako; dvoumni ali zastareli cilji se zavrnejo. | P |
| `set_component_fixed` | Ta kos fiksiraj oziroma ga sprosti za premikanje. | sprememba modela | Točen primerek najvišje ravni sestava. | — |
| `set_component_rotation` | Zasukaj ta plavajoči kos na navedene kote in ohrani položaj. | sprememba modela | Absolutni koti; ne popravlja vezi. | — |
| `set_component_translation` | Premakni ta plavajoči kos na navedene koordinate in ohrani zasuk. | sprememba modela | Ena komponenta najvišje ravni; preveri pričakovani stari položaj. | — |
| `standard_library_status` | Preveri stanje naše knjižnice standardnih delov. | pregled | Poroča stanje kataloga in navodilo za osvežitev. | — |
| `suppress_component` | Ta kos izključi oziroma ga ponovno vključi. | sprememba modela | Izključitev ne izbriše komponente; spremeni stanje sestava. | — |
