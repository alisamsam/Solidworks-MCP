# Volumensko modeliranje — uporabniški primeri

Stanje: 2026-10-19; 35 registriranih orodij.

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
| `add_equation` | Dodaj novo imenovano globalno spremenljivko s številčno ali tekstovno vrednostjo. | sprememba modela | Tekst je shranjen kot tekstovni izraz; za urejanje obstoječe enačbe drugo orodje. | P |
| `apply_material` | Temu kosu dodeli izbrani material iz naše baze. | sprememba modela | Točen material in datoteka baze; vpliva na izračun mase. | P |
| `boundary_boss` | Med dvema ali tremi profili naredi mejni volumen. | sprememba modela | Ena smer; brez poljubnih pogojev tangentnosti. | P |
| `boundary_cut` | Med dvema ali tremi profili naredi mejni izrez. | sprememba modela | Omejeni native način, ne vse možnosti Boundary. | P |
| `chamfer_edges` | Na teh robovih naredi posnetje 1 mm pod kotom 45 stopinj. | sprememba modela | Podprto kot/razdalja ali dve razdalji; pravilni robovi v partu. | P |
| `circular_pattern` | To funkcijo ponovi okoli izbrane osi. | sprememba modela | Določi točno funkcijo, os, število in kot. | P |
| `combine_bodies` | Ti dve telesi združi, odštej ali ohrani njun presek. | sprememba modela | Potrebna je ustrezna geometrijska medsebojna lega. | P |
| `create_configuration` | Dodaj novo konfiguracijo z navedenim imenom. | sprememba modela | Ne prepiše obstoječe konfiguracije. | P |
| `create_coordinate_system` | Ustvari koordinatni sistem s tem izhodiščem in zasukom. | sprememba modela | Navedi XYZ in po potrebi kote. | P |
| `create_reference_axis` | Ustvari referenčno os v presečišču teh dveh ravnin. | sprememba modela | Dve različni točno imenovani ravnini. | P |
| `create_reference_plane` | Ustvari ravnino 50 mm od izbrane ravnine. | sprememba modela | Podprt odmik; ne vsi načini definiranja ravnin. | P |
| `create_sketch_on_planar_face` | Na tej točno določeni ravni ploskvi odpri skico. | sprememba modela | Izbor z native indeksom namesto ugibanja po koordinati. | — |
| `cut_extrude` | S to skico izreži material do navedene globine. | sprememba modela | Predhodno preverimo skico, telo in smer. | P |
| `delete_body` | Iz naše kopije odstrani to telo oziroma ohrani samo njega. | sprememba modela | Pred posegom preverimo pravi indeks telesa. | P |
| `dome` | Na tej ravni ploskvi naredi kupolo. | sprememba modela | Določi ploskev in višino. | P |
| `draft_faces` | Tem ploskvam dodaj navedeni izvlečni naklon glede na nevtralno ploskev. | sprememba modela | Določi ploskve, nevtralno ploskev, kot in smer. | P |
| `extrude_sketch` | To skico iztisni 20 mm v določeno smer. | sprememba modela | Izdelava volumna iz skice, ne pločevinasta definicija. | — |
| `fillet_edges` | Na teh potrjenih robovih naredi zaokrožitev R2. | sprememba modela | Orodje za part; izbor sestavne komponente še ne omogoči Edit Part. | P |
| `hole_wizard` | Na tej ploskvi naredi izvrtino M6 po DIN, skozi vse. | sprememba modela | Določimo vrsto/standard/velikost in mesto; navojne in cevne luknje niso potrjen obseg. | P |
| `insert_part` | V ta part vstavi geometrijo drugega shranjenega kosa. | sprememba modela | Doda stock telo; ni vstavljanje komponente sestava. | P |
| `linear_pattern` | To funkcijo ponovi vzdolž določene smeri. | sprememba modela | Potrebni so točna funkcija, smer, razmik in število. | P |
| `list_features` | Pokaži zgodovino funkcij tega modela. | pregled | Imena uporabimo za nadaljnje natančne posege. | P |
| `loft_cut` | Med temi profili naredi prehodni izrez. | sprememba modela | Določi zaporedje profilov. | P |
| `loft_sketches` | Med temi profili v tem vrstnem redu naredi prehod. | sprememba modela | Vrstni red profilov vpliva na geometrijo. | P |
| `mirror_feature` | To funkcijo zrcali čez navedeno ravnino. | sprememba modela | Točni imeni funkcije in ravnine. | P |
| `move_copy_body` | To telo premakni za dani XYZ; po želji ohrani original kot kopijo. | sprememba modela | Telesa znotraj parta, ne komponenta sestava. | P |
| `revolve_cut` | S tem profilom izreži material okoli njegove osi. | sprememba modela | Zaprti profil z eno konstrukcijsko osjo. | P |
| `revolve_sketch` | Ta profil zavrti okoli njegove konstrukcijske osi. | sprememba modela | Profil in os morata biti pripravljena. | P |
| `rib` | Iz te odprte skice naredi ojačitveno rebro. | sprememba modela | Obstoječ solid, konstantna debelina, brez naklona rebra. | P |
| `scale_body` | To telo enakomerno povečaj z navedenim faktorjem. | sprememba modela | Enakomerno skaliranje okoli izhodišča ali težišča. | P |
| `set_appearance` | Temu kosu nastavi dogovorjeno barvo. | sprememba modela | Barva na ravni kosa in aktivne konfiguracije. | P |
| `set_custom_property` | Temu kosu nastavi opis, šifro ali drugo tekstovno lastnost. | sprememba modela | Lastnost dokumenta ali točno določene konfiguracije. | P |
| `shell_feature` | Ta kos izvotli na navedeno debelino in odpri izbrane ploskve. | sprememba modela | Najprej natančno določimo odstranjene ploskve. | P |
| `sweep_cut` | Po tej poti izreži kanal s tem profilom. | sprememba modela | Zaprt profil in ločena skica poti. | P |
| `sweep_sketch` | Ta zaprt profil potegni po navedeni poti. | sprememba modela | Ločeni skici; začetek poti mora ustrezati profilu. | P |
