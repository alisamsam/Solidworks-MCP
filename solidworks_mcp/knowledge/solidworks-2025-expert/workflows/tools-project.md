# Projektne kopije in spremembe — uporabniški primeri

Stanje: 2026-10-19; 33 registriranih orodij.

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
| `apply_parameter_changes` | Na preverjenih kopijah uporabi te dogovorjene spremembe mer. | projektni poseg | Delna napaka ne pomeni samodejne razveljavitve prejšnjih korakov. | — |
| `build_manufacturing_package` | Za preverjeno kopijo pripravi izbrane native, STEP, DXF in tabelarične izhode. | projektni poseg | Paket poroča tudi delne napake; ni avtomatična izdelovalna potrditev. | — |
| `check_interferences` | V sestavu preveri dejanske volumenske trke in udeležene kose. | izbor/pogled/stanje | Odsotnost trka ne dokazuje stika ali zahtevanega odmika. | — |
| `checkpoint_project` | Iz shranjenega stanja pripravi novo preverjeno kontrolno kopijo. | projektni poseg | Zavrne neshranjene spremembe; ne shranjuje izvirnika. | — |
| `compare_project_versions` | Primerjaj ti dve shranjeni projektni kopiji in njune spremembe. | pregled | Datoteke/parametri/masa niso splošen dokaz geometrijske enakovrednosti. | — |
| `copy_project` | Iz tega projekta naredi neodvisno testno kopijo z vsemi referencami. | projektni poseg | Nova dovoljena mapa, unikatna imena, relink in preverjene izvirne kontrolne vsote. | P |
| `create_persistent_reference` | Za to funkcijo ustvari in preveri trajno native referenco. | pregled | Funkcije, ne poljubne ploskve; vezano na dokument in konfiguracijo. | — |
| `edit_component_pattern` | V tej obstoječi ponovitvi komponent spremeni število ali razmik. | sprememba modela | Podprti linearni vzorec; omejitve konfiguracij. | — |
| `edit_feature_definition` | Temu obstoječemu iztisu spremeni globino ali podprti končni pogoj. | sprememba modela | Omejena vrsta funkcij/konfiguracij; ni splošen urejevalnik vseh definicij. | — |
| `edit_mate` | Tej obstoječi razdaljni ali kotni vezi spremeni gonilno mero. | sprememba modela | Ne zamenjuje poljubnih referenc vezi. | — |
| `import_neutral_file` | Uvozi navedeni STEP, IGES, Parasolid ali SAT za nadaljnji pregled. | sprememba modela | Uvoz ne zagotovi parametrične zgodovine ali popolne geometrije. | — |
| `import_parameter_workspace` | Iz obstoječih mer naše kopije pripravi nov projekt v registru. | projektni poseg | Ne spreminja mer modela. | — |
| `inspect_holes_and_fasteners` | Pokaži native funkcije izvrtin Hole Wizard in Hole Series. | pregled | Iz premera ne prepozna vijaka; ne pregleda sam vseh kosov sestava. | — |
| `inspect_model_health` | Preveri napake funkcij in manjkajoče reference modela. | pregled | Ne nadomesti geometrijskega ali izdelovalnega pregleda. | — |
| `inspect_parameter_dependencies` | Pokaži reference dokumentov, skupne pojavitve in gonilne enačbe. | pregled | Ne sklepa vseh manjkajočih konstrukcijskih odvisnosti. | — |
| `inspect_part_manufacturing` | Preglej telesa tega kosa, razrezni seznam in možnosti razreza pred izvozom. | pregled | Bere trenutno geometrijo brez osveževanja. Plošča je le geometrijski kandidat; material in make/buy nista potrjena. | P |
| `inspect_project_references` | Pred kopiranjem preveri vse shranjene reference projekta. | pregled | Ne odpira ali spreminja izvirnikov; manjkajoče reference so ovira. | P |
| `list_model_parameters` | Pokaži obstoječe gonilne mere in parametre tega modela. | pregled | Ne izmišljuje pomena posamezne mere. | P |
| `make_component_independent` | Samo ta primerek naredi neodvisen od ostalih ponovitev. | projektni poseg | Nova kopija referenc in zamenjava enega primerka; preverimo vezi. | — |
| `manage_configurations` | Pokaži konfiguracije ali preklopi na navedeno obstoječo konfiguracijo. | projektni poseg | Ne ustvarja, preimenuje ali briše konfiguracij. | — |
| `manage_external_references` | Preglej zunanje reference tega dokumenta. | pregled | Zaklep, odklep, prekinitev in relink v tem orodju niso omogočeni. | — |
| `plan_assembly_documentation` | Za ta sestav pripravi seznam kosov, količine in načrt map za delavniške, sestavne in montažne risbe ter izvoze. | izhodna datoteka | Čist shranjen sestav in nova mapa; načrt JSON/CSV/Markdown, brez dejanskih PDF/DXF/STEP. Vrsto teles in make/buy preverimo posebej. | P |
| `present_result` | Odpri točno naš preverjeni rezultat in ga pripravi za pregled. | projektni poseg | Aktivacija ne zagotovi, da ga uporabnikov zaslon dejansko prikazuje. | — |
| `process_parameter_workspace_job` | Izvedi eno že pripravljeno zahtevo iz registra in zapiši rezultat. | projektni poseg | Lahko shrani spremenjene kopije; zahteva preverjene immutable podatke naloge. | — |
| `read_parameter_workspace` | Pokaži naš register projektnih parametrov, osnutke in zahteve. | pregled | Register brez povezave s CAD ni trenutna geometrija modela. | — |
| `rename_project_documents` | V novi kopiji projekta preimenuj navedene datoteke in popravi reference. | projektni poseg | Nikoli ne preimenuje izvirnikov na mestu. | — |
| `replace_component` | Ta primerek sestava zamenjaj z navedeno datoteko. | sprememba modela | Samo preverjena kopija; po zamenjavi preverimo vezi. | P |
| `replace_structural_profile` | Temu členu varjenca zamenjaj profil z drugim iz knjižnice. | sprememba modela | Preverjen tip člena, ena konfiguracija in znana stara pot profila. | — |
| `resolve_persistent_reference` | Preveri, ali ta shranjena referenca še kaže na isto funkcijo. | pregled | Brez nadomestnega iskanja po podobnem imenu. | — |
| `set_model_dimension` | To obstoječo gonilno mero spremeni s stare na novo vrednost. | sprememba modela | Preverjena delovna kopija, prava konfiguracija in pričakovana stara mera. | P |
| `update_drawing_package` | Obnovi povezane risbe naše kopije in preveri liste. | projektni poseg | Samo izrecno povezane risbe; shranjevanje je posebej določeno. | — |
| `update_model_equation` | Spremeni navedeno obstoječo enačbo modela. | sprememba modela | Izrecno pričakovani stari izraz in nova vrednost. | T |
| `write_parameter_workspace` | V register zapiši parameter ali osnutek spremembe. | projektni poseg | Sam zapis še ne spremeni CAD modela. | — |
