# 04 Assembly Modeling — navodila za obdelavo

## Vloga in obseg modula

Assembly Modeling je sestavljanje posameznih Part datotek v funkcionalno celoto. SOLIDWORKS sestav (.sldasm) ne kopira geometrije komponent — samo hrani reference (poti do datotek) in definicijo odnosov med njimi (Mates). Vsaka sprememba Part datoteke se samodejno odraža v vsakem sestavu, ki ta Part vsebuje — to je najmočnejša lastnost parametričnega sistema.

---

## Kaj poudariti

### Osnove vstavljanja komponent

**Vstavljanje novega kosa:**
- Insert > Component > Existing Part/Assembly → izberi datoteko
- Drag & Drop iz Design Library ali iz Windows Explorerja
- Insert > Component > New Part → ustvari nov Part znotraj sestava (Top-Down)

**Stopnje prostosti (Degrees of Freedom — DOF):**
- Prosto telo v 3D prostoru ima 6 DOF: 3 translacije (X, Y, Z) + 3 rotacije (Rx, Ry, Rz)
- Cilj Mating je reducirati DOF na 0 (fully constrained)
- Priporoča se: ne prekorači DOF (over-constrained) → SW bo javljal napake

**Prva komponenta:**
- Vedno vstavi "base component" (npr. ohišje, okvir) in jo **fiksaj** (Fix)
- Desni klik na komponento > Fix → komponenta je pritrjena na koordinatno izhodišče

**Statusni indikatorji v FeatureManagerju:**
- **(-)** → Under-defined (premalo matov — komponenta se še premika)
- **(+)** → Over-constrained (preveč matov — konflikt)
- Brez oznake → Fully constrained
- **(f)** → Fixed (fiksna)
- **(?)** → Ni rešena (mate conflict)

---

### Standard Mates

**Coincident**: dve površini isti ravnini, dve točki na isti točki, rob na rob
- Odstranjuje: 1 translacijo + 2 rotaciji (za ravnino na ravnino)
- Tipična raba: ravna stena na ravno steno

**Concentric**: dve osi sta koaksialni
- Odstranjuje: 2 translaciji (komponenta se še rotira in premika vzdolž osi)
- Tipična raba: bat v cilindru, vijak v luknji

**Parallel**: dve površini vzporedni (ampak ne nujno na isti ravnini)
- Odstranjuje: 2 rotaciji
- Tipična raba: vzporedni plošče

**Perpendicular**: dve površini sta pravokotni
- Odstranjuje: 1 rotacijo

**Tangent**: krivina tangira ravnino ali drugo krivino
- Odstranjuje: 1 DOF
- Tipična raba: ležajni prstan na ohišje

**Distance**: razdalja med dvema elementoma
- "Flip Dimension": razdalja na eno ali drugo stran → koristno za simetrijo

**Angle**: kot med dvema elementoma

**Lock Rotation**: prepreči rotacijo pri Concentric matu (fiksira osi, ne samo pozicijo)

**SmartMates:**
- Med vlečenjem komponente v sestav → SW pre