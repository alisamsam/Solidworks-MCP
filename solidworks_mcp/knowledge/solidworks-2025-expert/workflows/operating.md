# Delo z MCP: vrstni red, izbira, okrevanje

Za uporabniška naročila in pregled vseh področij začni z [uporabniškim vodičem](tools.md).
Novemu orodju dodaj primer in mejo v `scripts/user_tool_examples.txt`, nato obnovi
navodila z `python scripts/build_user_tool_guide.py`. Preverjanje `--check`
zavrne manjkajoča orodja in zastarele generirane strani.

Status: operativna pravila za vse postopke; niso dokaz posameznega modela.
Preberi pred prvo CAD mutacijo v seji. Trenutna shema orodja ima prednost
pred katerimkoli primerom v navodilih.

## Mentalni model

- Strežnik ne hrani namere. Vsak klic je samostojen; namero drži model in jo
  prevaja v majhne korake. Eno orodje, en učinek.
- Dokument je stanje, ne kontekst. Aktivni dokument se lahko zamenja. Za
  zaporedje mutacij uporabi `bind_active_document`; po `TargetMismatchError`
  ne nadaljuj na slepo, ampak ponovno ugotovi stanje.
- Geometrija je revizijsko vezana. Indeksi ploskev, robov in komponent veljajo
  samo za trenutno revizijo; vsaka mutacija ali zavrženi poskus jih lahko
  preštevilči.
- Uspeh je dokaz, ne odsotnost napake. Nekateri API klici vrnejo void ali
  "success" brez učinka. Po operaciji preberi nazaj in navedi, kaj si videl.
- Meje (`guarded_mode`, izhodne in zaščitene poti) so v strežniku. Če naloga
  zahteva pot izven odobrenih map, povej uporabniku; ne išči obvoda.

## Vrstni red pred spremembo

1. **Namera.** Končni artefakt: part, sestav, risba, pločevina, varjenec,
   izvoz. Če je več poti, izberi eno in jo povej.
2. **Povezava.** `connect_solidworks`, `get_solidworks_info`.
3. **Stanje.** `list_open_documents`, `inspect_document`; cilj veži z
   `open_document` ali `bind_active_document`. Neshranjen dokument vrne
   "Not saved" namesto poti.
4. **Enote.** Eksplicitne (privzeto mm).
5. **Reference.** Pred izbiro naštej: `list_planes`, `list_planar_faces`,
   `list_component_faces`, `list_body_edges`, `list_features`.
6. **Operacija.** Eno mutacijsko orodje na korak. Pred prvim klicem preberi
   shemo orodja (npr. ime argumenta poti ni povsod enako).
7. **Verifikacija.** Preberi nazaj: `list_features`, `get_body_bounding_box`,
   `get_mass_properties`, `measure_distance`, `inspect_model_health`.
8. **Shranjevanje.** V okviru naročene dobave in v odobreno pot, samo za
   dokumente, ki jih upravlja ta avtomatizacija. Uporabnikovih že odprtih delov
   in neznanih ročnih sprememb ne shranjuj ali zavrzi. Dovoljena mapa ni
   dokaz lastništva. Naše poskuse lahko zapreš brez shranjevanja, če obstaja
   shranjen izhod ali navedena obnovitvena skripta; sicer ostanejo odprti.

## Varno shranjevanje in zapiranje

MCP beleži svoje novo ustvarjene dokumente. Čist dokument, odprt na novo,
prevzame samo ob dokazanem izvoru iz potrjenega shranjevanja ali uspešnega
`copy_project` v tej seji in ob ujemajočem se SHA datoteke. Dovoljena mapa
sama ne zadošča; tudi uporabnikov prej zaprt kos ostane zaščiten.
Že naložen dokument se s ponovnim `open_document` ali
`bind_active_document` ne spremeni v naš dokument. Native update-stamp in dirty
zastavica se primerjata z zadnjo znano MCP operacijo; ročnih posegov ne izvajaj
sočasno s klicem MCP, ker njihovega izvora med samim klicem ni mogoče zanesljivo ločiti.

`save_document` brez poti še vedno izbere `<output_root>/<subfolder>/<title>`.
Ko je izračunani cilj ista normalizirana pot, uporabi skupni Save3; za nov
cilj SaveAs. Obe veji vrneta napake in opozorila, upoštevata varovanje poti
ter ohranita registry preverjanje. SaveReferenced ni samodejno vključen.
Spremembe referenc v dejanskem SolidWorksu preveri na izolirani kopiji pred
uporabo v proizvodnem projektu. Na uporabnikovem dokumentu save ni dovoljen
niti pod drugo potjo. `USER_DOCUMENT_PROTECTED` ni razlog za obvoz varovala.
Obstoječega tujega cilja ne prepiše niti SaveAs našega dokumenta. Zunanjo
spremembo že zapisanega našega izhoda zazna SHA in prepreči samodejni prepis.
Izvor je namerno lokalen seji: neznanega starega izhoda ne prevzemi na podlagi
imena ali mape; pripravi novo preverjeno delovno kopijo. To kopira datoteke,
ne zahteva ponovnega modeliranja vseh delov.

`close_document(save=true)` ob neuspešnem shranjevanju dokument pusti odprt.
Če gre za naš obnovljivi izhod, lahko nato izrecno uporabiš `save=false`.
Za naš neshranjeni izhod navedi obstoječo berljivo obnovitveno skripto prek
`recovery_script`; to je pot za obnovitev, ne potrditev pravilnosti modela.
Sama skripta nikoli ne dovoli zavrženja uporabnikovih sprememb.
Po delno neuspešni MCP operaciji se spremenjeni izhod ne shrani samodejno;
lahko se popravi/preveri ali varno zavrže. Skupinsko čiščenje ohrani tuje dokumente.

## Izbira in indeksi

Pravilen vzorec: naštej → izberi → ena operacija → preveri → ponovno naštej.
Napaka: stari indeks uporabljen za drugo mutacijo.

| Orodje | Vir reference | Kaj zastari |
|---|---|---|
| `export_face_to_dxf`, `measure_distance`, `shell_feature` | `list_planar_faces` | indeks ploskve po spremembi geometrije |
| `mirror_feature`, `create_reference_plane` | `list_planes` (+ `list_features`) | natančno ime ravnine/funkcije |
| `linear_pattern`, `circular_pattern`, `sweep_sketch`, `loft_sketches` | `list_features` | natančno ime funkcije ali skice |
| `mate_*` | `list_component_faces` | indeksi po vsaki vezi ali premiku |
| `trim_entities`, `extend_entities` | imena segmentov skice | trim razveljavi prejšnje entitete |

Kjer orodje sprejme ime, uporabi ime; nikoli si ga ne izmišljuj. Ime ravnine
("Top") ni dokaz orientacije: po potrebi preveri normalo.

## Okrevanje

1. Ne ponavljaj istega klica na slepo.
2. `get_solidworks_info` → `inspect_document` / `list_open_documents` →
   `bind_active_document` → pri skici `get_sketch_status` → `get_capabilities`.

| Simptom | Verjeten vzrok | Ukrep |
|---|---|---|
| `TargetMismatchError` | aktivni dokument se je zamenjal | ponovno stanje, nato bind |
| `VALIDATION_FAILED` | argument ne ustreza shemi | preberi `data.argument` in namig; popravi ime ali vrednost, ne ponavljaj enakega klica |
| mutacija se tiho ne zgodi | skica ni zaprta | `get_sketch_status` → `close_sketch` |
| "success" brez vidne spremembe | API ni ustvaril učinka ali je učinek zanemarljiv | preveri volumen/telesa; sicer "ni potrjeno" |
| napačna ploskev | zastarel indeks | ponovno naštej |
| izvoz zavrnjen | pot izven odobrenih map | odobrena mapa ali brez poti |
| modalno okno (npr. izjema dodatka) | okno blokira avtomatizacijo | uporabnik ga zapre ročno; nato ponovno stanje |
| `swFileLoadError`, malo virov okna | preveč odprtih dokumentov | zapri shranjene izhodne dokumente (ne izvirnikov, ne neshranjenih) |
| `capture_view` odpove | okno ni vidno | uporabnik naj ne minimizira okna |
| počasen sistem, `The interface is unknown` ali manjkajoče COM metode pozno v dolgi seji | zasičen GPU pomnilnik (glej spodaj) | `get_solidworks_info` → `session.gpu_dedicated_mb`; shrani, nato `restart_solidworks` |

**GPU pomnilnik v dolgi seji.** SolidWorks ob zaprtju okna dokumenta ne vrne
grafičnega pomnilnika do ponovnega zagona: izmerjeno ~36 MB na dokument, ko
se zapre zadnje okno (celotna grafična površina se zgradi na novo), in
~8 MB, dokler je odprto drugo okno. Geometrija na to ne vpliva; skrit
dokument ne pušča, a ne more biti `ActiveDoc`, zato ni uporaben za orodja.
Pri zaporedju, ki odpre in zapre veliko dokumentov (gradnja kosov iz skripte,
testi), naj bo ves čas odprt en dokument (sidro), npr. sestav ali prazen
neshranjen del, ki se zapre na koncu. Po več sto odprtih dokumentih ali ob
upočasnitvi shrani delo in ponovno zaženi SolidWorks.

`get_solidworks_info` v `session` poroča `gpu_dedicated_mb` in
`restart_recommended` (prag 4096 MB). `restart_solidworks` se zavrne, dokler je
odprt neshranjen, spremenjen ali dokument izven odobrenih izhodnih map; brez
`confirm=true` samo vrne, kaj bi zaprl. `confirm=true` pošlji šele, ko je
uporabnik ponovni zagon odobril. Po zagonu je seja prazna: dokumente odpri
znova in ponovno veži cilj.

Strežnik po vsakem orodju šteje odprte in zaprte dokumente in občasno vzorči
GPU pomnilnik (`session.counters`). Ob ≥ 4096 MB ali ≥ 200 zaprtih dokumentih
doda v odgovor opozorilo "Long SolidWorks session" (največ na 15 min). Takrat
dokončaj trenutni korak, predlagaj shranjevanje in vprašaj uporabnika za
ponovni zagon; `close_saved_outputs` zapre samo shranjene izhodne dokumente.

- **`operation_id`** je idempotenten ključ: ponovitev z istim ključem vrne
  zapisan izid brez ponovne izvedbe. Uporabi ga, ko prejšnji odgovor ni
  prišel. Za drugačno operacijo nov ključ.
- **Meja treh poskusov.** Po treh iteracijah brez napredka se ustavi in
  poročaj: kaj si poskusil, kaj je vrnil strežnik, kaj predpostavljaš.
- Ob napaki nikoli ne shranjuj, da bi "rešil" stanje, in ne posegaj v
  uporabnikove ročno odprte dokumente.
- En klient in ena skripta naenkrat: COM se veže na eno instanco SolidWorks.
- Za kopiranje projekta uporabi `copy_project`; `pack_and_go` je blokiran.
  Razpoložljivost preveri z `get_capabilities`, ne s starim seznamom.

## Ponovljiva avtomatizacija

Ko se ista zaporedja klicev ponavljajo z drugimi merami, loči izračun od CAD:
vhodni podatki (JSON) → čist planer brez COM → kandidati → nova varianta v
novi mapi ali lokalni popravek dovoljene delovne kopije po varnostni točki → nativna verifikacija z zapisom
dokaza → zapiranje shranjenih izhodov. Vsak korak naj preveri status dokaza
prejšnjega. Enolična imena datotek po reviziji preprečijo, da sestav poveže
napačno kopijo z istim imenom.

## Popravek sestava: spremeni samo razliko

Ko je sestav že odprt ali shranjen, ga ne gradi znova in ne poganjaj cele
gradbene skripte. Najprej `assembly_diff` s seznamom želenih komponent (ime,
pot, položaj v mm, potlačenost, fiksiranost); vrne manjkajoče, odvečne,
premaknjene in spremenjene. Za eno komponento `get_component` (vključno z
njenimi vezmi). `list_components(mode="fast")` nima transformov ali stanj.
Nato popravi samo razliko:

| Želena sprememba | Orodje |
|---|---|
| dodati komponento | `insert_component` + `add_mate` |
| odstraniti komponento (z vezmi) | `remove_component` (potrebuje ime in trenutno pot) |
| začasno izklopiti, kasneje vrniti | `suppress_component` |
| zamenjati z drugim modelom | `replace_component` |
| preimenovati instanco | `rename_component` (potrebuje trenutno pot) |
| premakniti, zasukati, fiksirati | `set_component_translation`, `set_component_rotation`, `set_component_fixed` (trenutno stanje iz `get_component`) |
| dodati vez (vse pogoste vrste) | `add_mate` |
| odstraniti napačno vez | `delete_mate` (`name` in `feature_type` iz `list_mates`, npr. `MateCoincident`), nato `add_mate` |
| spremeniti vrednost vezi ali vzorec | `edit_mate`, `edit_component_pattern` |
| spremeniti mero dela | `set_model_dimension`, `edit_feature_definition` |

Ponovno gradnjo ali celo skripto uporabi samo, če se je spremenil večji del
sestava ali če izhodišče ne obstaja. Po vsaki spremembi preveri stanje z
`list_components` in šele nato shrani.

[Parametrični del](part.md) · [Sestav](assembly.md)
