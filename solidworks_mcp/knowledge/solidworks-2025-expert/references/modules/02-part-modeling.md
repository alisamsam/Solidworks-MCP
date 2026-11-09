# 02 Part Modeling — navodila za obdelavo

## Vloga in obseg modula

Part Modeling je jedro SOLIDWORKS — tukaj nastajajo tridimenzionalni kosi. Temelji na parametričnem, featurami osnovanem modeliranju: vsak kos je zaporedna serija featurejev (Extrude, Fillet, Hole...), ki jih SW ob vsaki spremembi parametra samodejno pošlje skozi rebuild. To je Design Intent — kos mora biti zgrajen tako, da se "inteligentno" prilagaja.

---

## Kaj poudariti

### Sketching — temelj vsega

Skoraj vsak feature začne z 2D skico. Kakovost skice = kakovost featureja = stabilnost modela.

**Osnovna pravila skiciranja:**
- Skica mora biti **fully defined** (črna barva entitet) — ne under-defined (modra) in ne over-defined (rdeča)
- **Under-defined** skica: nekdaj entitete niso vpete z relacijami ali merami → ob rebuild se premikajo nepredvidljivo
- **Over-defined** skica: preveč omejitev, ki si med seboj nasprotujejo → model se ne rebuilda

**Sketch entitete:**
- Line, Circle, Arc (3-point, Center, Tangent), Rectangle (Corner, Center, 3-Point), Polygon
- Ellipse, Parabola, Spline (Control Polygon), Style Spline
- Slot (Straight, Centerpoint, 3-Point Arc, Centerpoint Arc)
- Point, Centerline, Construction Line

**Sketch orodja:**
- **Trim Entities**: reži prekrivajočo geometrijo (Power Trim = drag za hitro rezanje)
- **Extend Entities**: podaljšaj do reference
- **Offset Entities**: odmik konture za določeno razdaljo
- **Convert Entities**: projiciraj robove 3D telesa v skico (kritično za referenciranje!)
- **Intersection Curve**: presečišče dveh površin kot skična entiteta
- **Mirror Entities**: zrcalij geometrijo okrog osi
- **Linear/Circular Sketch Pattern**: ponovi skično geometrijo

**Sketch Relations (Geometric Relations) — osnova fully defined:**

| Relacija | Opis | Tipična raba |
|----------|------|-------------|
| Coincident | Dve točki sta isti točki | Zapiranje konture |
| Collinear | Dve črti sta na isti premici | Ravne reference |
| Parallel | Dve črti sta vzporedni | Simetrija |
| Perpendicular | Dve črti sta pravokotni | Pravokotne stene |
| Tangent | Krivulja in rob sta tangentna | Gladki prehodi |
| Equal | Enaka dolžina ali radij | Simetrični elementi |
| Symmetric | Simetrija okrog osi | Osno simetri