# 24 Costing / Sustainability / Xpress — navodila za obdelavo

## Opomba — izključeni moduli

**FloXpress** ni predmet poglobljene obravnave, ker je Flow Simulation (modul 12) izključen.

## Kaj poudariti

### Costing
- **Costing** — samodejni izračun proizvodnih stroškov na osnovi modela in predlog
- **Sheet Metal Costing** — strošek pločevinastih kosov (material, laserji, krivljenje...)
- **Machining Costing** — strošek strojno obdelanih kosov (surovex, operacije, čas)
- **Multibody Costing** — stroškovna analiza za modele z več telesi
- **Costing Templates** — predloge z urnimi postavkami, materiali, operacijami
- **Material Costs** — cene materiala (€/kg) — zahtevajo ažurne tržne podatke
- **Manufacturing Operation Costs** — stroški posameznih operacij (laser, krivljenje, vrtanje...)
- **Cost Reports** — poročila in primerjave

### Sustainability
- **Sustainability** — okoljska primerjava materialov in transportnih scenarijev
- Primerja CO₂ odtis, porabo energije, vpliv na vodo
- Pomaga pri odločanju med materiali z okoljskega vidika

### Xpress orodja
- **DFMXpress** — Design for Manufacturability: avtomatično preverjanje oblikovnih pravil (min. debelina, min. radij, luknje...)
- **SimulationXpress** — poenostavljena statična FEA za hitro oceno napetosti (brez polnega Simulation modula)
- **DriveWorksXpress** — osnovna parametrična avtomatizacija design variant
- **TolAnalyst** — statistična tolerančna analiza v sestavih

## Obvezne usmeritve

- Pri **Costing** opozori: rezultati so odvisni od **kakovosti vhodnih podatkov**:
  - Napačne cene materiala, operacij ali urnih postavk = napačen strošek
  - Costing je orodje za orientacijo, ne nadomestek kalkulacije v ERP
- Pri **material costs** razloži potrebo po **ažurnih cenah**:
  - Cene kovin se dnevno spreminjajo — predloga mora biti redno posodobljena
  - Starela predloga → izkrivljeni stroški
- Pri **costing templates** razloži standardizacijo:
  - Template vsebuje: urne postavke, strošek operacij, rezalne standarde, material cenik
  - Standardizirana predloga zagotavlja primerljive kalkulacije med projekti
- Pri **Sustainability** razloži:
  - Primerja alternativne materiale in načine dobave po CO₂ in energijskem odtisu
  - Ni zamenjava za certificirani LCA (Life Cycle Assessment) — je orientacijski prikaz
- Pri **Xpress orodjih** razloži **omejitve v primerjavi s polnimi moduli**:
  - SimulationXpress: samo statična analiza enostavnih partov, brez kontakta, assembly, mesh control
  - DriveWorksXpress: omejena pravila, brez naprednih workflow funkcij polnega DriveWorksa
  - TolAnalyst: omejena na 1D tolerančno analizo

## Tipični primeri podtem

- Costing (Sheet Metal, Machined Part)
- Costing Template konfiguracija
- Material in operation cost management
- Cost Reports
- Sustainability analiza
- DFMXpress
- SimulationXpress (orientacijska FEA)
- DriveWorksXpress
- TolAnalyst
