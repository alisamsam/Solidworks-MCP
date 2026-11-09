# Risanje skic — uporabniški primeri

Stanje: 2026-10-19; 34 registriranih orodij.

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
| `close_sketch` | Zaključi trenutno aktivno skico. | sprememba modela | Zapiranje skice ni shranjevanje dokumenta. | — |
| `convert_entities` | Robove te ploskve prenesi v aktivno skico. | sprememba modela | Nekaj usklajenih robov; množična pretvorba vseh robov ni zanesljiva. | P |
| `create_3d_sketch` | Odpri 3D skico za osi profilov varjenca. | sprememba modela | Točke so v koordinatah modela. | P |
| `create_centered_profile_sketch` | Iz potrjene geometrije pripravi centrirano skico profila v novem kosu. | projektni poseg | Poskusni part; ne namesti ali prepiše profila v knjižnici. | — |
| `create_sketch` | Na navedeni ravnini odpri novo skico. | sprememba modela | Določi ravnino in namen skice. | — |
| `create_sketch_on_face` | Odpri skico na ploskvi pri navedeni točki. | sprememba modela | Koordinate lahko zadenejo napačno ploskev; indeksni način je natančnejši. | — |
| `create_sketch_on_plane` | Odpri skico na točno imenovani standardni ali lastni ravnini. | sprememba modela | Uporabi obstoječo ravnino. | P |
| `draw_arc` | Nariši lok s središčem, radijem ter začetnim in končnim kotom. | sprememba modela | Pozitivna smer je nasprotna urnemu kazalcu. | P |
| `draw_arc_3point` | Nariši lok od te točke do druge skozi tretjo. | sprememba modela | Tretja točka določa stran loka. | P |
| `draw_arc_slot` | Nariši ukrivljeno režo s središčem loka in navedeno širino. | sprememba modela | Določi središče, začetek in konec loka. | P |
| `draw_arc_slot_3point` | Nariši ukrivljeno režo skozi tri točke in z navedeno širino. | sprememba modela | Točke ležijo na središčnici reže. | P |
| `draw_center_rectangle` | Nariši pravokotnik 100 × 50 mm okoli tega središča. | sprememba modela | Lahko ustvari konstrukcijske diagonale; pri revolve to upoštevamo. | P |
| `draw_centerline` | Nariši konstrukcijsko središčnico za os vrtenja. | sprememba modela | Konstrukcijska geometrija ne postane obris materiala. | P |
| `draw_circle` | Nariši krog z navedenim središčem in radijem. | sprememba modela | Osnovno orodje uporablja sejne enote; radij ni premer. | — |
| `draw_circle_radius` | Nariši krog s središčem tukaj in radijem 10 mm. | sprememba modela | Radij ni premer. | P |
| `draw_ellipse` | Nariši elipso z navedenima polosema in zasukom. | sprememba modela | Polosi niso celotna širina in višina. | P |
| `draw_elliptical_arc` | Nariši del elipse med navedenima parametričnima kotoma. | sprememba modela | Ne navaden krožni lok. | P |
| `draw_equation_curve` | V skici nariši krivuljo po podani enačbi y=f(x). | sprememba modela | Določi izraz, območje in enote. | P |
| `draw_equation_curve_3d` | V 3D skici nariši krivuljo x(t), y(t), z(t). | sprememba modela | Tri enačbe in interval parametra t. | P |
| `draw_line` | V aktivni skici nariši črto med tema točkama. | sprememba modela | V 2D skici uporabljamo njene lokalne koordinate. | — |
| `draw_line_3d` | V 3D skici nariši črto med navedenima XYZ točkama. | sprememba modela | Izrecni tridimenzionalni krajišči. | — |
| `draw_parabola` | Nariši parabolični segment iz gorišča, vrha in krajišč. | sprememba modela | Potrebne so geometrijsko skladne točke. | P |
| `draw_parallelogram` | Nariši paralelogram skozi te tri vogale. | sprememba modela | Vrstni red vogalov je pomemben. | P |
| `draw_point` | V aktivni skici dodaj točko. | sprememba modela | Določi koordinate in enoto. | P |
| `draw_polygon` | Nariši pravilen šestkotnik okoli tega središča. | sprememba modela | Določi število stranic, velikost in orientacijo. | P |
| `draw_rectangle` | Nariši pravokotnik med nasprotnima vogaloma. | sprememba modela | Dimenzije oziroma koordinate morajo biti določene. | — |
| `draw_rectangle_3point_center` | Nariši zasukan pravokotnik iz središča in dveh dodatnih točk. | sprememba modela | Točke določijo položaj in smer širine. | P |
| `draw_rectangle_3point_corner` | Nariši pravokotnik iz treh vogalnih točk. | sprememba modela | Prvi dve točki določita prvi rob. | P |
| `draw_sketch_text` | V skico dodaj besedilo na dogovorjeni položaj. | sprememba modela | Skicno besedilo, ne opomba tehnične risbe. | P |
| `draw_slot` | Nariši ravno podolgovato režo z danima središčema in širino. | sprememba modela | Širina reže in razdalja središč sta različna podatka. | P |
| `draw_spline` | Nariši zlepek skozi te urejene točke. | sprememba modela | Točke morajo biti v pravilnem zaporedju. | P |
| `draw_tangent_arc` | Iz tega krajišča nadaljuj s tangentnim lokom do te točke. | sprememba modela | Začetek mora biti krajišče obstoječega segmenta. | P |
| `get_sketch_status` | Povej, katera skica je aktivna in katere obstajajo. | pregled | Uporabno pred risanjem ali iztiskanjem. | — |
| `inspect_construction_geometry` | Preberi to skicno črto oziroma preveri profil konstrukcijskega člena. | pregled | Sredina obsega krajišč ni splošno težišče krivulje. | — |
