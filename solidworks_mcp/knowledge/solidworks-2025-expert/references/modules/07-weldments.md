# 07 Weldments & Structures — navodila za obdelavo

## Vloga in obseg modula

Weldments & Structures je SOLIDWORKS workflow za modeliranje jeklenih konstrukcij, ogrodij, regalov, varjencev in profilnih struktur. Ključna razlika od Assembly modeliranja je, da je varjenec **en sam Part** — ne sestav komponent. Vsi profili so "bodies" (telesa) znotraj istega dokumenta, popisani v Cut List (seznam rezov), ne v BOM.

**Ključni princip**: Varjenec = en Part z več solid bodies. Assembly BOM → ne rabimo. Cut List → to je naš seznam.

---

## Kaj poudariti

### 3D Sketch kot osnova varjenca

**Kdaj 3D Sketch, kdaj 2D Sketch:**
- Za ravninska ogrodja (npr. miza, polica) je dovolj 2D Sketch na Front Plane
- Za prostorske konstrukcije (npr. kletka, prostorska rešetka) je potreben 3D Sketch
- 3D Sketch = eno samo skicirno okolje z X, Y, Z hkrati

**Ustvarjanje 3D Sketch:**
- Insert > 3D Sketch → aktivira 3D skicirno okolje
- Tab tipka: preklaplja aktivno ravnino (XY, YZ, ZX)
- Smart Dimension v 3D Sketchu: kotira razdalje in kote v prostoru

**Dobra praksa:**
- Najprej nariši "ogrodje" brez profilov — samo linijska skica strukture
- Vse linije se stikajo v skupnih točkah — SW potrebuje zaprte segmente za pravilen trim

---

### Structural Members

**Vstavljanje:**
- Insert > Weldments > Structural Member → PropertyManager
- Izberi Standard (ISO, DIN, ANSI, AISC, ...)
- Izberi Type (square tube, rectangular tube, c channel, i beam, angle, pipe, ...)
- Izberi Size (npr. "50x50x3")
- Klik na segmente skice → SW vstavi profil vzdolž vsakega segmenta

**Orientacija profila:**
- Rotation Angle: zasuk profila okrog osi segmenta (v stopinjah)
- Mirror Profile: zrcali profil
- Locate Profile: nastavi, katera točka profila leži na skici (centroid, corner, midpoint)
- **Napačna orientacija = profil je zarotiran ali obraten** → vedno preveri v 3D pogledu po vnosu

**Profili v eni skupini:**
- Segmenti v isti skupini → SW jih prereže kot kontinuirani profil brez stika
- Nova skupina → SW generira miter/butt joint med skupinami

---

### Profile Library — knjižnica profilov

**Vgrajena knjižnica:**
- Lokacija: `[SOLIDWORKS Install]\lang\english\weldment profiles\`
- Standardne knjižnice: ISO, ANSI/AISC, DIN, GB (kitajski standard)

**Pot v System Options:**
- Tools > Options > System Options > File Locations > Weldment Profiles → dodaj pot do las