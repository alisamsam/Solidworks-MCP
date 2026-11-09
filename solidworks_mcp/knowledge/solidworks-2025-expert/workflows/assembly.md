# Sestava: najprej obseg, nato komponente in vezi

Status: priporočeni postopek, ne potrjen celoten proizvodni primer.

1. Preveri odprte dokumente in izberi ciljno sestavo. Za orientacijo uporabi
   list_components(mode="fast", depth=1). Podrobne transforme in globlji
   pregled zahtevaj samo za potrebno vejo. Izpuščeni podatki v fast niso
   dokaz, da ni konfiguracije ali potlačenih komponent.
2. Zapiši, kateri del je baza, kateri so premični, katere konfiguracije in
   vmesniki so potrebni. Standardni del poišči v katalogu in izberi velikost;
   po vstavitvi preveri dejansko velikost, ne samo ime konfiguracije.
3. Vstavljaj po potrjenem položaju in enotah sheme orodja. Za vezi ponovno
   pridobi ploskve obeh komponent. Po vsaki vezi preveri stanje in položaj;
   indeksi pred premikom niso trajne reference.
4. Preveri rešenost in namen vezi, število komponent in sklice na datoteke.
   Osnovne vezi ne pomenijo podpore vsem vrstam gibanja ali dokaza, da ni
   kolizij. Dodatno kontrolo izvedi s preverjenim razpoložljivim postopkom
   oziroma jasno označi ročno kontrolo.
5. Pri prilagajanju obstoječega projekta najprej uporabi
   [kopiranje projekta](project-copy.md). `copy_project` kopira in preveri
   reference brez blokiranega Pack and Go. Pri predaji ponovno preveri poti
   do vseh uporabljenih dokumentov in stanje vezi.

## Vezi po imenu

`add_mate` sprejme za vsako referenco `face_index` ali ime ravnine ali osi
komponente (`"Front Plane"`, `"Axis1"`). Imenovana referenca ostane
veljavna po vsaki novi vezi, `face_index` pa ne, zato je za ponovljive
popravke boljša. Kadar je vez napačna: `list_mates`, `delete_mate`, nato
`add_mate`. Kot (`angle`) se poda v stopinjah, razdalja (`distance`) v
milimetrih. Če ravnina ali os ni najdena, orodje vrne napako z imenom
reference; takrat uporabi `face_index`. Preimenovanje (`rename_component`)
ne uspe, če je v SolidWorksu vklopljena možnost "Update component names
when documents are replaced"; orodje to javi, nastavitve pa ne spreminja.

## Pregled stanja sestava

Pred shranjevanjem preveri, brez novih orodij: `list_mates` vrne za vsako vez
stanje reševanja (`solved`, `warning`, `error`, `unknown`); vez z napako ali
opozorilom odpravi (`delete_mate`, `add_mate`) ali povej uporabniku.
Preveč določene vezi se pokažejo kot napaka ali opozorilo, ne kot posebno
stanje: odstrani odvečno vez, ne dodajaj nove. `check_interferences` prijavi
trke, ne pa stika. Število komponent primerjaj z `assembly_diff`.
Strategijo izberi vnaprej: komponente po delih (od spodaj navzgor), ko so deli
neodvisni; okvir iz skice ali dela v sestavu (od zgoraj navzdol) samo, če
mere morajo slediti skupni skici. Pri velikih sestavih zahtevaj samo
potrebno vejo (`list_components` depth=1, nato globlje).

## Znane pasti

- AddComponent5 postavi komponento po svojem središču, ki ni središče
  bounding boxa. Po vstavitvi preberi Transform2. Prvo vstavljeno komponento
  fiksiraj (`set_component_fixed`).
- Položaj, nastavljen s transformom, ni vez. Za risbe in spremembe mer
  dodaj vezi; brez njih sestav ni parametričen.
- Enaka osnovna imena datotek v različnih revizijskih mapah povzročijo, da
  SolidWorks naloži napačno kopijo. Uporabi enolična imena po reviziji in
  preveri pot vsake komponente.
- Odsotnost interference ne dokazuje stika. Stik preveri posebej z
  razdaljo med ploskvama.
- Zrcaljenje predloge, katere izhodišče ni v središču:
  tx_novo = 2·m − tx − 2·cx (m je zrcalna ravnina, cx lokalno središče).
- Preveč naloženih dokumentov vodi v `swFileLoadError` ali pomanjkanje virov
  okna. Zapri samo shranjene izhodne dokumente brez shranjevanja; nikoli
  izvirnikov ali neshranjenih dokumentov.
- Modalno okno dodatka (npr. izjema Inspection) blokira avtomatizacijo,
  dokler ga uporabnik ne zapre.

[Assembly Modeling](../references/modules/04-assembly-modeling.md)

### Izbor robov v točnem kosu

Najprej preberi native Name2 poti komponent. `list_component_edges` sprejme
točno pot (npr. `SUB-1/BLOCK-2`), ne samo ime datoteke ali končnico poti.
Uporabi filtre curve_type/body_index/min_length_mm ali near_point_mm+within_mm
v globalnih koordinatah sestava v mm. body_index je native indeks solidov
komponente, ne vidni Save Bodies indeks. next_offset je naslednji native rob;
complete velja le za pregledano stran. Krogi brez ločenih oglišč so vključeni.

Za izbor uporabi snapshot_id in edge_ids iz iste strani v isti MCP seji.
`select_component_edges` preveri native lastnika/identiteto/mark. append ohrani
stari izbor, isti rob+mark se ne podvoji. Ob napaki preveri selection_restored;
če je False, izbora ne uporabljaj. Snapshot poteče po15min ali32novejših
straneh; po spremembi dokumenta/configuracije/kosa/transforma seznam osveži.
Izbor zahteva odobreno delovno kopijo; brez samodejnega resolve/Edit Part/save.
Obstoječa fillet/chamfer orodja s tem še ne dobijo urejanja v sestavu.

### Sporazumevanje prek SVG oznak

`export_component_edge_svg(component_path, output_path, view='isometric', offset=0,
limit=40)` izdela nov SVG in spremljevalni JSON. Prvi obseg je ena komponenta,
ne pregled celotnega sestava. Uporabniku pokaži prikaz in navedi njegov naziv;
oznako R7 vedno poveži s tem prikazom/map_id. Ime kosa ni dokaz identitete.
`select_component_svg_edges(map_id, labels=['R7'], append=False, mark=0)` razreši
oznako prek strežniških persistent referenc in preveri dejanskega lastnika.
SVG/JSON sta arhiv; njuno urejanje ne preusmeri povezave. Izvoz ne spremeni
modela/izbora in ne shranjuje CAD. Oba izhodna dokumenta morata biti nova.

Pogledi isometric/xy/xz/yz so žične projekcije s skritimi robovi, ne HLR/izdelovalne
risbe. Enote iz modela so mm, prikaz je fit-to-page. Krogi/loki so vzorčeni do5°.
Nepodprta krivulja ali nedoločljiva smer polkroga nima oznake; completeFalse in
warnings zahtevata pregled. complete velja za stran, next_offset vodi naprej.
Ločeni klicni napisi in depth interval pomagajo razlikovati robove. Enake zaznane
projekcije ali rob, projiciran v točko, se ne izberejo: pripravi drug pogled.
To ne rešuje vseh presečišč in prekrivanj cele scene.

Povezava je trenutno samo za isto MCP sejo,15min/32strani; po restartu/spremembi
modela ustvari nov SVG. To še ni prepoznavanje prostoročne puščice ali samodejen
native izbor ob kliku na SVG. Najprej razreši oznako v pravi rob, nato posebej
določi spremembo in uporabi modelirno orodje. Podrobnosti procesa:
`docs/upgrade/plans/SVG-MODEL-LINK-R01.md`.

Za DXF ene pločevine iz večtelesnega parta ne izvažaj po starih indeksih:
`export_sheet_metal_body_dxf` uporablja svež vidni body_index/update_stamp in
izolirano kopijo, ker native export preureja telesa in naredi aktivni model dirty.
To ni izvozni ukaz za poljubno komponento sestava; najprej odpri pravo delovno
part kopijo. Glej uporabniške primere `workflow/tools-sheetmetal`.
