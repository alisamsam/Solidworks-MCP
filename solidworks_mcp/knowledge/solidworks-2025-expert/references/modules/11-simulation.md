# 11 Simulation (FEA) — navodila za obdelavo

## Opomba — izključeni moduli

**Flow Simulation (modul 12) je izključen.** Ne obravnavaj CFD, tokovnih analiz, aerodinamike, HVAC, toplotnih prenosov prek tekočin.

Kadar se tema nanaša na Flow Simulation: "Ta funkcionalnost ni predmet tega workbooka, ker je modul Flow Simulation izključen."

## Kaj poudariti

- **Osnovi FEA koncepti**: diskretizacija, vozlišča, elementi, enačbe ravnotežja
- **Materiali**: dodelitev materiala, elastičnost, Poissonovo razmerje, gostota
- **Fixtures** (robni pogoji): Fixed, Roller/Slider, Hinge, Advanced...
- **Loads** (obtežbe): Force, Pressure, Gravity, Torque, Remote Load...
- **Mesh**: globalna in lokalna gostota, mesh control, Curvature-based vs. Standard
- **Static Study** — osnovna statična analiza napetosti in pomikov
- **Stress / Strain / Displacement** — interpretacija rezultatov
- **Factor of Safety** — varnostni koeficient glede na mejo tečenja
- **Contact** — NoContact, Bonded, Surface-to-Surface, Shrink Fit...
- **Connectors** — Bolt, Pin, Spring, Elastic Support...
- **Frequency Study** — lastne frekvence in nihajne oblike
- **Buckling Study** — kritična obtežba za izvlek (uklonski faktor)
- **Thermal Study** — stacionarna in prehodna toplotna analiza (brez tekočin)
- **Fatigue Study** — utrujanje pri ciklični obtežbi
- **Drop Test Study** — udarni test
- **Nonlinear Study** — velika deformacija, kontakt, nelinearna materialna obnašanja
- **Dynamics Study** — modalna, harmonična, naključna, transientna analiza
- **Topology Study** — optimizacija oblike za zmanjšanje mase
- **Results Interpretation** — skalarna polja, vektorji, animacije

## Obvezne usmeritve

- Pri vsaki analizi razloži **vhodne podatke** (material, fixture, load, mesh).
- Pri **fixtures** opozori:
  - Nerealna vpetja (npr. Fixed na veliko površino) dajo nerealistične rezultate
  - Vpetje mora posnemati realne pogoje — kako je kos dejansko pritrjen?
- Pri **loads** opozori:
  - Smer obremenitve je kritična — napačna smer = napačni rezultati
  - Razloži razliko med Force (absolutna sila) in Pressure (tlak na površino)
- Pri **mesh** razloži pomen **konvergence**:
  - Rezultati morajo biti stabilni pri zgostiti mrežice (mesh refinement)
  - Brez preverjanja konvergence FEA rezultati niso zanesljivi
- Pri **rezultatih** razloži:
  - Barve vizualizirajo napetosti — toda samo gledanje barv ni dovolj
  - Absolutne vrednosti (von Mises stress, max displacement) morajo biti primerjane z materialnimi lastnostmi
  - Posebej opozori na **singularnosti**: visoke napetosti v konicah (notch, pointed corners) so artefakti mreže, ne realna stanja
- **Ne obravnavaj** CFD, tokovnih analiz, aerodinamike.

## Tipični primeri podtem

- Static Study (setup, fixtures, loads, mesh, solve, results)
- Factor of Safety
- Mesh Control in Convergence
- Contact (Bonded, No-Penetration, Surface-to-Surface)
- Connectors (Bolt, Pin, Spring)
- Frequency Study
- Buckling Study
- Thermal Study (brez CFD)
- Fatigue Study
- Drop Test
- Nonlinear Study
- Topology Study
- Result Plots (Stress, Displacement, Strain, FOS)
- Poročilo simulacije
