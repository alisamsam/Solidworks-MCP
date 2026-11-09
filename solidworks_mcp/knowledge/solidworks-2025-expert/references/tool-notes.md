# Opombe k orodjem

Status: podrobnosti, odstranjene iz opisov orodij zaradi velikosti kataloga.
Veljajo skupaj s trenutno shemo orodja; shema ima prednost.

## `create_tab_and_slot`

Rob zavihka mora ležati v ravnini površine utora, na drugem telesu, obrnjen proti
pločevini, skozi katero gre. Na ravnih pločevinah je zavihek raven prst; na profilih
(cevi) je to robni rob ene cevi, ki raste skozi steno druge, zato kot
`tab_height_mm` podaj debelino te stene, da se zavihek konča poravnano z notranjo
ploskvijo. `tab_face_index` je izbirna ravninska ploskev debeline zavihka ob izbranem
robu; pri poševnem koncu cevi uporabi steno cevi. Uspeh je javljen samo, ko eno telo
pridobi material in drugo ga izgubi. `tab_thickness_mm` privzeto sledi debelini pločevine.

## `create_weldment_gusset`

Ploskvi morata gledati v notranjost stika (pri T-stiku: ploskev prehodnega člena in
bližnja ploskev pritrjenega člena) in se srečati v pravem robu, zato mora prehodni
člen segati čez stik. Rezultat poroča skupni volumen trdnine pred in po, tako da je
dodana plošča dokazljiva. `use_length_dim` uporabi `leg4_mm` namesto `angle_deg`;
`use_length_dim_for_chamfer` uporabi `chamfer2_mm` namesto `chamfer_angle_deg`.
`reverse_face` zamenja `leg1/leg2` (pri poligonu tudi `leg3/leg4`). `crv_index` izbere
rob, kadar se seka več robov.

## `create_weldment_end_cap`

Brez `face_indices` zapre ravninske konce, pravokotne na najdaljšo os člena.
`direction='inward'` postavi pokrov na oddaljeno stran končne ploskve, poravnano z njo;
`'outward'` ga izstopi; `'inset'` ga umakne za `inset_mm`. Rezultat poroča skupni
volumen pred in po. `given_offset=true` uporabi `offset_value_mm`, sicer
`wall_thickness_ratio` (razmerje glede na steno člena).

## `create_structural_member`

Uporabi vse segmente poimenovane skice; ustvari mapo Weldment, če je ni. Povezane
segmente drži v eni skupini z izbirnimi zajeri, nepovezane količke daj v ločene
skupine (`separate_groups` je potreben za nepovezane količke z istim profilom).
`group_mode`: `auto` = privzeta ena skupina, `all` = vsi segmenti v eni skupini ne
glede na povezanost, `per_segment` = ena skupina na segment. `corner_type='miter'`
nastavi swEndConditionMiter. `segment_indices` (vrstni red iz `get_sketch_status`)
omogoča več profilov iz ene skice. `allow_protrusion` privzeto true.

## `edit_component_pattern`

Ureja število primerkov v smeri 1 enokonfiguracijske kopije sestava z LocalLPattern,
njeno izrecno obstoječo dimenzijo razmika v trenutni konfiguraciji, ali zaduši
LocalLPattern/LocalCirPattern. Preveri branje nazaj; ne shrani. Konfiguracija mora biti
aktivna (nikoli se tiho ne preklopi); `edit_original` ne obide pravil zaščitenih poti.

## `insert_standard_part`

Razreši del iz sinhronizirane knjižnice in delegira `insert_component`. S `size=` se vstavi
točno ta velikost Toolboxa: del se sproti pripravi (zapisljiva kopija se preklopi na
konfiguracijo velikosti, obnovi, shrani in vstavi). Vijaki zahtevajo `size=`; njihova
nekonfigurirana PreviewCfg/privzeta geometrija ni prava velikost. Matice DIN 934,
podložke DIN 125A M3–M30 in ISO 4762 M10x25 se pripravijo iz glavnih kopij s preverbo
geometrije. Položaj x,y,z je v metrih, privzeto 0.

## `edit_feature_definition`

Ureja globino naprej in slepi/srednjeravninski končni pogoj enokonfiguracijske kopije dela
z Boss/Cut ali zaduši podprte funkcije v točno trenutni konfiguraciji. Preveri
branje nazaj/obnovo; ne shrani. Konfiguracija mora biti aktivna; `edit_original` ne
obide pravil zaščitenih poti.

## `create_configuration`

Doda eno poimenovano konfiguracijo, zavrne prepis obstoječe in prebere shranjeno
konfiguracijo nazaj. `alternate_name` se shrani samo, če `options` vsebuje
swConfigOption_UseAlternateName (1). `options` je bitna maska swConfigurationOptions2_e;
128 (swConfigOption_DontActivate) pusti aktivno konfiguracijo nespremenjeno. `comment`
je komentar v Configuration Properties; `description` besedilo, ki opredeli konfiguracijo.

## `edit_mate`

Ureja izrecno imenovan obstoječi pogon razdalje/kota ali zaduši podprt zvez v točno
aktivni konfiguraciji preverjene kopije sestava. Zavrne driven in z enačbo krmiljene
mere. Ne shrani. Konfiguracija mora biti aktivna; `edit_original` ne obide pravil
zaščitenih poti.

## `insert_component`

Položaj je v metrih v prostoru sestava. Privzeto (`place='center'`, obnašanje
AddComponent5) pristane središče omejevalnega kvadra dela na točki; `place='origin'`
postavi izhodišče dela na točko, kar zahteva že odprt del. `configuration`
je izbirno ime konfiguracije, npr. velikost Toolboxa 'ISO 4762 M10 x 16 - 16N';
privzeto privzeta konfiguracija dela.

## `remove_component`, `suppress_component`, `rename_component`

Vse tri delujejo na natančno ime komponente najvišje ravni (brez `/`). `remove_component`
in `rename_component` zahtevata trenutno pot (`expected_path`). Odstranitev uporabi
`DeleteSelection2(swDelete_Absorbed=2)` in preveri, da je seznam komponent skrčen natanko za eno.
Potlačitev velja za aktivno konfiguracijo; prebrano stanje 2 ali 3 pomeni razrešeno.
`rename_component` ne uspe, dokler je vklopljena možnost External References > "Update
component names when documents are replaced" (toggle 18); orodje je ne spreminja. Imena brez
`/ @ < >`.

## `delete_mate`, `add_mate`

`delete_mate` zahteva `name` in `feature_type` iz `list_mates` (npr. `MateCoincident`);
`MateGroup` in `MateReference*` zavrne. `add_mate` podpira coincident, concentric, parallel,
perpendicular, tangent, distance, angle, lock (width ni podprt). Referenca je `face_index`
ali ime ravnine/osi komponente; imenovana referenca je stabilna po novi vezi. Samo komponente
najvišje ravni. Razdalja v mm, kot v stopinjah. Stanje `AddMate5` je v `add_mate_status`;
vrednost, ki ni 1, doda `warning` (vez obstaja, preveri `list_mates`). Tip osi `AXIS` in ime
feature tipa `MateLock` še nista živo potrjena.

## `assembly_diff`, `get_component`, `set_component_rotation`

`assembly_diff` primerja samo komponente najvišje ravni (`list_components(depth=1)`);
neznani ključi v `expected` so napaka. `complete` je false tudi, kadar branje ni popolno.
`get_component` vrne `translation_mm`, `rotation_deg` in vezi, ki se dotikajo komponente.
`set_component_rotation`: `[rx, ry, rz]` v stopinjah, Rz·Ry·Rx (X prvi), desnosučno okoli
izhodišča komponente; `ArrayData` je v konvenciji vrstičnega vektorja (kot `_local_to_global`).
`expected_rotation_deg` mora ustrezati trenutnemu stanju (toleranca 1e-4 na matriki).
Pri gimbal lock (ry = ±90°) se vsa vrednost zapiše v rx. Smer zasuka še ni živo potrjena.

## `create_component_pattern`

Linearni ali krožni vzorec ene komponente najvišje ravni. `reference` je smer (linearni)
oz. os (krožni): `face_index` iz `list_component_faces` (ravna ploskev / valj) ali ime
`plane`. Živo potrjeno (SolidWorks 2025): linearni z ravno ploskvijo in z ravnino, `reverse`,
krožni z valjno ploskvijo (`angle_deg` 360 = enakomerno okoli kroga). Neuspešen izbor
reference ne ustvari značilke. Pazi: izvorna komponenta mora imeti izbor z oznako 1, smer/os
z oznako 2 (orodje to naredi samo); napačne oznake dajo tiho `CreateFeature` = None.
Imena ravnin so odvisna od dela (`Plane1` ali `Front Plane`). Referenca `axis` po imenu
še ni živo potrjena. Zrcaljenje komponent (`MirrorComponents3`) ni implementirano.
