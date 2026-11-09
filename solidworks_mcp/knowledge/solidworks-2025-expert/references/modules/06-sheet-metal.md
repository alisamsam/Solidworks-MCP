# 06 Sheet Metal — navodila za obdelavo

## Vloga in obseg modula

Sheet Metal je specializirani workflow za modeliranje elementov, ki bodo narejeni iz ravnega materiala z upogibanjem. SOLIDWORKS Sheet Metal je parametričen — vsaka sprememba debeline, radija ali K-faktorja samodejno posodobi model IN razviti plašč (Flat Pattern). Flat Pattern je osnova za lasersko rezanje, vrezovanje in žigosanje.

**Ključni princip**: Sheet Metal model ima vedno dve "resničnosti":
1. **Upognjena oblika** (3D model) — za sestav in vizualizacijo
2. **Flat Pattern** — razviti plašč za proizvodnjo

---

## Kaj poudariti

### Sheet Metal osnovna nastavitev

Ko začneš Sheet Metal model, moraš definirati tri temeljne parametre:
- **Thickness (debelina)**: debelina pločevine v mm (ali inch)
- **Bend Radius (notranji radij krivljenja)**: najmanjši radij, ki ga stroj izvede brez trganja
- **K-factor**: razmerje med nevtralno osjo in debelino

**Pravilo za osnovno nastavitev:**
- Tool > Sheet Metal → nastavi pred prvim featurjem
- Ali: pri prvem feature-ju (Base Flange) definiraj vse tri parametre

---

### K-factor — razlaga

K-factor definira, kje leži "nevtralna os" pri upogibanju — del materiala, ki se ne razteza niti stiska.

| Material | Tipičen K-factor |
|----------|-----------------|
| Mehko jeklo (S235, S275) | 0.33 |
| Nerjavno jeklo (304, 316) | 0.38–0.43 |
| Aluminij (Al 6082) | 0.40–0.45 |
| Medenina | 0.38–0.42 |

**Formule:**
- Bend Allowance (BA) = π × (Bend Radius + K × Thickness) × Angle / 180
- Razvita dolžina = Vsota ravnih segmentov + Σ(BA za vsak upogib)

**Napačen K-factor** = napačna dolžina razvitega plašča → kos se ne sklene ali pa je predolg.

**Bend Deduction (BD) kot alternativa K-factorju:**
- BD = 2 × (Bend Radius + Thickness) × tan(Angle/2) − BA
- Bend Deduction je mehaniška razlaga (koliko materiala "vzame" upogib)
- Nekateri stroji ali stranke podajajo BD namesto K-faktorja

---

### Gauge Tables

Gauge Tables so tabele, ki standardizirajo nastavitve za specifičen material in stroj.

**Vsebina Gauge Table:**
- Gauge Number → debelina (mm ali inch)
- Bend Radius za vsak Gauge
- K-factor ali Bend Deduction za vsak Gauge in material

**Lokacija:**
- `[SOLIDWORKS Install]\lang\english\Sheet Metal Gauge Tables\`
- System Options > File Locations > Sheet Metal Gauge Tables → doda pot

### MCP: zavih roba (Hem), preverjeno 18. 10. 2026

`create_sheet_metal_hem` (sheetmetal) podpira odprt/zaprt zavih enega ravnega
roba zložene enotelesne pločevine. Najprej shrani odobreno delovno kopijo in
preberi sveže `list_body_edges`; podaj edge_index,length_mm, hem_type,
za open gap_mm (privzeto1) in po potrebi reverse. Zaprt hem ne sprejme gap_mm;
native residual gap se vrne posebej in se ne prikazuje kot nič.
Notranji položaj ter parent bend allowance/default relief; drugi tipi,
outside, več robov/teles in custom relief ostajajo nepreverjeni.
Po ustvarjanju preveri `get_flat_pattern_info` pred namernim shranjevanjem.
API uspeh zahteva native parametre, persistent Hem brez napak, rebuild,
spremenjeno geometrijo in enako debelino; sam klic ne shranjuje.

### MCP: več pločevinskih teles v enem partu

Prvo telo ustvari z `create_sheet_metal_base_flange` kot doslej. Shrani našo
odobreno delovno kopijo. Za naslednje telo ustvari svežo skico z ločenim
obrisom in pokliči isto orodje z `new_body=true`, debelino in radijem.
PrivzetiFalse ščiti pred nenamernim drugim telesom. Native per-body override
ohrani stare geometrije in omogoča različne debeline; neposredno spreminjanje
skupne Sheet-Metal debeline bi spreminjalo tudi starejše kose.
Preverjeni zaprti obrisi in debeline1/2/3mm v istem partu; dodatni odprti
profili, gauge tabele ter večtelesni flatten/DXF še niso dokaz tega načina.
Po dodajanju ponovno preberi indekse; rebuild lahko regenerira native telesa.
`get_sheet_metal_info` ostaja pregled prve definicije, ne vseh teles.
Orodje samo ne shranjuje; po CAD napaki pusti model za pregled in ne naredi undo.

### MCP: pregled nastavitev po telesih

`list_sheet_metal_bodies` (sheetmetal, READ) vrne vsa sheet telesa z njihovimi
native Sheet-Metal/Flat-Pattern imeni, thickness_mm,bend_radius_mm,K-factor
in bend_allowance_type ter suppression stanjem. Skrita telesa so vključena;
navadni solidi so ločeno navedeni brez pločevinskih mer. `body_index` je vidni
Save Bodies indeks; `solid_body_index` vključuje skrita telesa in ni zamenljiv.
Po odprtju/spremembi ponovno preberi indekse. Pred uporabo zahtevaj completeTrue
in preglej warnings; manjkajoča/dvoumna ali nezdrava definicija ni uspešno branje.

K-factor se vrne samo pri aktivnem načinu2; pri table/direct/deduction/calculation
je None. `flattened` pomeni native Flat-Pattern suppression stanje, ne dokaz
pravilne geometrije za izdelavo. Branje ne razvija teles, ne rebuilda in ne
spreminja izbire/save flaga. `get_sheet_metal_info` še naprej bere prvo definicijo.
