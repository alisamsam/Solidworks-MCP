# 01 Core Platform — navodila za obdelavo

## Vloga in obseg modula

Core Platform zajema temeljno infrastrukturo SOLIDWORKS: nastavitve programa, standardizacijo dokumentov, upravljanje datotek in konfiguriranje delovnega okolja. Vse kar določa "kako se SW obnaša" spada sem. To so nastavitve, ki niso del modeliranja, a odločilno vplivajo na kakovost, ponovljivost in vzdržljivost vsega dela.

---

## Kaj poudariti

### System Options vs. Document Properties

**System Options** (Tools > Options > System Options):
- Veljajo za **celoten program** na tem računalniku — za vse dokumente, vse projekte, vse uporabnike tega profila
- Shranjene v Windows registru ali user profilu
- Ključne kategorije:
  - **General**: enote privzetega novega dokumenta, potrditveni dialogi, samodejno shranjevanje
  - **Drawings**: privzete nastavitve prikazov, kotiranja, view labels, display quality
  - **Sketch**: privzeti vzorci in načini skiciranja, over-defined opozorila, Relations/Snaps
  - **Performance**: Use Software OpenGL, Transparency, No Preview During Open, Detailing mode
  - **File Locations**: NAJPOMEMBNEJŠE — poti do Templates, Toolbox, Weldment Profiles, Sheet Formats, Custom Symbols, Hole Wizard baze
  - **Backup/Recover**: interval samodejnega shranjevanja, število varnostnih kopij, lokacija

**Document Properties** (Tools > Options > Document Properties):
- Veljajo samo za **aktivni dokument** (odprti Part, Assembly ali Drawing)
- Shranjene znotraj same SOLIDWORKS datoteke (.sldprt/.sldasm/.slddrw)
- Ključne kategorije:
  - **Units**: enota (mm/inch/cm), natančnost prikaza (decimalna mesta)
  - **Draftin