# Varjeni okvir, stopnice in ograja: od referenc do kosovnice

Status: priporočeni postopek; posamezne operacije imajo ločene dokaze.
Celotna izdelava stopniščne ograje še zahteva preizkus na ločenem projektu.

1. **Vhodni podatki.** Potrdi izmero, končni pod/oblogo, referenco višine
   ograje, profil, polnila, pritrditve in površinsko zaščito. Naklon,
   prehodi in višina izhajajo iz potrjenih parametrov stopnic. Če je na voljo,
   uporabi mechanical-design-engineer za konstrukcijske odločitve in
   vprašanja. Sicer jih izrecno razjasni.
2. **Reference.** Pripravi osi poti in razdeli povezane segmente v smiselne
   skupine. Izberi dejanski knjižnični profil. Upoštevaj položaj profila
   glede na os: os poti ni nujno zunanja površina ali svetla odprtina.
3. **Členi in stiki.** Preveri orientacijo, dolžine, število teles in stike.
   Pred trim operacijo preberi njeno trenutno shemo. Miter brez reže ne
   pomeni podpore podaljšanju do ploskve. Za blokirane variante določi drugo
   preverjeno rešitev ali označen ročni korak.
4. **Pritrditev, ojačitve, zaključki.** Dodaj po potrjenem načrtu in
   preverjenih predpogojih. Kozmetični zvar je oznaka, ne dodan material ali
   dokaz nosilnosti zvara. Pri gusset/end-cap preveri ciljne ploskve.
5. **Cinkanje.** Pred zapiranjem votlih profilov razjasni prezračevanje,
   odtok in dostopnost odprtin po veljavnih navodilih izbrane pocinkovalnice.
   Če je konstrukterski skill nameščen, preberi njegovo vejo za cinkanje.
   Brez vira ne privzemi velikosti odprtin. End cap sam ni dokaz
   pripravljenosti izdelka za cinkanje.
6. **Kontrola.** Preveri svetle odprtine, odmik od pohodne površine,
   prehode, montažne mere, delitev za transport in podatke cut list. Pri
   spremembi višine/naklona ponovi odvisne kontrole. Geometrijska kontrola
   ni statični izračun ali dokaz skladnosti s predpisom.

## Znane pasti

- Varjenec lahko preklopi konfiguracijo (npr. AsMachined); po operaciji
  ponovno veži dokument in preveri aktivno konfiguracijo.
- Ravna ploskev RHS je ožja od ovojnice zaradi zaobljenih vogalov (npr.
  96 mm pri 100 mm profilu). Priključne plošče meri na ravno ploskev.
- Tab & Slot: zračnost se prišteje dvakrat po dolžini in enkrat po širini.
  "Success" ali brez spremembe geometrije lahko pomeni zanemarljiv rez;
  preveri volumen obeh teles. Potreben je zadosten odmik od robov. Na
  poševni ploskvi cevi nativni Tab & Slot lahko postavi oglišča izven
  ovojnice cevi; tam uporabi ročni izvlek/rez. Po zavrženem poskusu
  ponovno naštej ploskve.
- `save_bodies` (weldments): uporabi čisto shranjeno delovno kopijo v odobreni
  mapi, sveže body_index iz `list_body_edges`, nove poti kosov in izrecno pot
  sestava. Native lahko shrani izvor in preimenuje telesa; orodje vrne
  `source_file_changed` ter `source_save_required`. Izhode zapre/ponovno odpre
  in preveri geometrijo/reference. Obstoječo Save Bodies funkcijo ali izhod
  zavrne; posodabljanje in prenos cut-list lastnosti še nista podprta.
- Identiteta COM ovojnice roba ni identiteta roba v DXF; zaprti krožni robovi
  nimajo oglišč.

[Weldments](../references/modules/07-weldments.md)

## Razrezni seznam in telesa za izvoz

Uporabnikov privzeti način je **en weldment part z več telesi**, ki izhajajo
iz več črt na isti skici. Ločene skupine Structural Member ne pomenijo ločenih
part datotek. Enaki členi se lahko združijo v isto cut-list postavko, telesa
pa ostanejo posamezno izbirna. Save Bodies je neobvezen izvoz po potrebi.

`get_cut_list_body_map` (weldments, READ) prebere obstoječe native cut-list mape
in telesa, brez osveževanja modela. Pred izvozom zahtevaj `mapping_complete=True`
in preglej opozorila. `body_count` je native število teles v postavki;
`body_index` je trenutni vidni indeks, ki ga sprejme `save_bodies`.
Skrita telesa imajo `body_index=null` in ločen `solid_body_index` v seznamu
vseh teles; tega indeksa ne podajaj Save Bodies. Indekse ponovno preberi
po odprtju, urejanju, spremembi konfiguracije ali vidnosti. Dva 250-mm člena
lahko delita postavko, posamezen indeks pa še vedno izbere eno konkretno telo.

Raw/evaluated lastnosti so native besedilo z `was_resolved` in result code;
`properties_freshness=not_verified` ne jamči aktualnih razreznih mer/enot.
`bounding_box_mm` je globalna ovojnica, ne razrezna dolžina. Za osveževanje
stari `get_cut_list` poseže v model; delaj samo na odobreni delovni kopiji,
nato ponovno preberi povezavo. Save Bodies še vedno zahteva čisto shranjeno
delovno kopijo in nove poti ter ne prenaša custom lastnosti.

## Izvrtine za pritrditev

`list_hole_wizard_sizes` (weldments) prebere lastni katalog brez CAD dokumenta.
Loči zračnost izvrtine, mere poglobitve in mere glave vijaka. Native_geometry_verified
False pomeni, da vsi kataloški zapisi še niso izdelani v CAD. `hole_wizard`
(features) nato uporabi izrecen `standard` in `catalog_size` ter zahtevane mere.
Podprti ANSI Metric, DIN in ISO; privzeto ostaja ANSI. Preverjeni so M6 primeri
Blind/Through All z ravno, cilindrično in stožčasto izvrtino. Več lokacij,
navojne/cevne/slot luknje ostajajo odprte.
