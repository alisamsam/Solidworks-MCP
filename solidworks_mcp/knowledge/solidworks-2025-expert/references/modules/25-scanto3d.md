# 25 ScanTo3D — navodila za obdelavo

## Kaj poudariti

- **Reverse Engineering** — postopek od fizičnega objekta do CAD modela
- **Mesh Import** — uvoz mrežnih datotek (STL, OBJ, PLY, XYZ...)
- **STL/OBJ podatki** — oblak točk ali trikotniška mreža iz 3D skenerja
- **Mesh Preparation** — priprava mreže pred rekonstrukcijo
- **Mesh Cleanup** — čiščenje šuma, lukenj, artefaktov skenerja
- **Curve Wizard** — samodejno ali ročno risanje krivulj po mreži (osnova za površinsko rekonstrukcijo)
- **Surface Wizard** — samodejno ali ročno ustvarjanje površin po krivuljah
- **Mesh to Surface Workflow** — celoten postopek od mreže do površine
- **Manual Reverse Engineering** — ročna metoda s skicami in referencami iz oblaka točk
- **Reference Sketches** — skice, ki se nanašajo na mrežo ali oblak točk
- **Deviation Analysis** — primerjava CAD modela in skena (barvna mapa odstopanj)
- **Solid Reconstruction** — pretvorba površine v solid telo

## Obvezne usmeritve

- Pri **mesh import** razloži vpliv velikosti datoteke:
  - Mreže iz industrijskih skenerjev so pogosto 50–500MB ali več
  - Prevelike mreže upočasnijo SOLIDWORKS — priporoča se decimacija mreže (redukcija trikotnikov) z zunanjim orodjem (MeshLab, Meshmixer) pred uvozom
- Pri **mesh cleanup** razloži tipične napake skena:
  - **Šum**: slučajne napake senzorja — čiščenje z Smooth/Denoise funkcijo
  - **Luknje**: manjkajoče površine tam, kjer skener ni videl — Fill Holes funkcija
  - **Artefakti**: prekrivajoče ali napačno orientirane površine — ročno brisanje
- Pri **Deviation Analysis** razloži:
  - Barvna mapa prikazuje razdaljo med CAD površino in izvornim skeniranim oblakom
  - Zelena = znotraj tolerance, rdeča = nad toleranco, modra = pod toleranco
  - Brez deviance analize ne veš, kako natančno je rekonstrukcija
- Pri **solid reconstruction** razloži razliko:
  - **Parametrični model**: zgrajen s featurji (Extrude, Revolve...) — popolnoma spremenljiv, a zahteva ročno rekonstrukcijo
  - **Površinska rekonstrukcija**: serija površin, ki opisijo obliko — manj prilagodljiv, a hitrejši za kompleksne organske oblike
- Posebej opozori: **avtomatska pretvorba skena v kakovosten CAD pogosto ni dovolj dobra**:
  - Surface Wizard da orientativni rezultat
  - Za inženirsko natančen CAD je pogosto potrebna **ročna rekonstrukcija** na osnovi skena kot reference

## Tipični primeri podtem

- Uvoz mesh datoteke (STL, OBJ)
- Mesh Cleanup in Preparation
- Decimacija mreže (zunanji korak pred uvozom)
- Curve Wizard
- Surface Wizard
- Ročna rekonstrukcija (skice po mreži)
- Reference Sketches iz oblaka točk
- Deviation Analysis
- Pretvorba v solid (Knit + Thicken)
- Reverse Engineering workflow (od skena do končnega CAD modela)
