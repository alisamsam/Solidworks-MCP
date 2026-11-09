# 21 Visualize — navodila za obdelavo

## Kaj poudariti

- **Import modelov** — SOLIDWORKS, STEP, OBJ, FBX...
- **LiveLink** — živa povezava med SolidWorks modelom in Visualize (samodejno posodabljanje)
- **Appearances** — materiali in površine za rendering (razlika od CAD materialov)
- **Materials** — fizikalno zasnovani materiali (PBR: difuz, odbojnost, hrapavost, metaličnost)
- **Textures** — UV preslikave, bump map, normal map, opacity
- **Decals** — nalepke, logotipi, napisi na površinah
- **Lighting** — točkast, smerni, areal, IBL (Image-Based Lighting)
- **HDR Environments** — panoramske HDR slike za osvetlitev in ozadje
- **Cameras** — definicija zornega kota, globinska ostrina, ekspozicija
- **Render Settings** — kakovost, vzorci, čas, šum
- **CPU / GPU Rendering** — razlike v hitrosti in kakovosti
- **Denoiser** — AI redukcija šuma za hitrejše renderje
- **Output Images** — resolucija, format, alfa kanal
- **Configurations** — prikaz različnih konfiguracij modela v Visualize
- **Animations** — orbitalna, kamerna, eksplozijska animacija
- **Turntable Animation** — rotirajoč prikaz modela za marketing

## Obvezne usmeritve

- Razloži razliko med **CAD materialom in render materialom**:
  - CAD material (SolidWorks): definira gostoto, Youngov modul za FEA in Costing — ni rendering material
  - Render material (Visualize Appearance): PBR material za fotorealistični prikaz — ni FEA material
  - Dve popolnoma ločeni bazi podatkov — nastavitve v enem ne vplivajo na drugega
- Pri **lighting** razloži vpliv na realističnost:
  - IBL (HDR) je najpreprostejša nastavitev za profesionalni izgled
  - Točkaste in smerne luči za poudarke, sence, dramatičen izgled
  - Kombinacija HDR + usmerjenih luči daje najboljši rezultat
- Pri **cameras** razloži:
  - **Kompozicija**: pravilo tretjin, vodilne linije, perspektiva
  - **Globinska ostrina (DoF)**: posnemanje fotografske optike — ozadje zamazano, ospredje ostro
  - **Ekspozicija**: nastavitev svetlosti slike
- Pri **render settings** razloži ravnotežje med kakovostjo in časom:
  - Nizki vzorci = hiter render, a vidni šum
  - Visoki vzorci = čist render, dolg čas
  - Denoiser skrajša čas za podobno kakovost
- Pri **GPU rendering** opozori na strojne zahteve:
  - Zahteva certificirano NVIDIA RTX grafično kartico z CUDA jedri
  - Brez ustrezne GPU se rendering vrne na CPU (počasnejši)
  - Preveriti: SOLIDWORKS Hardware Certification seznam

## Tipični primeri podtem

- Import in LiveLink nastavitev
- Appearances (PBR material workflow)
- Textures in Decals
- HDR Environment nastavitev
- Camera kompozicija in DoF
- Lighting (IBL, točkaste, smerne)
- Render Settings (kakovost vs. čas)
- CPU vs. GPU rendering
- Denoiser
- Output Images (resolucija, format, alfa)
- Konfiguracije v Visualize
- Turntable Animation
- Vizualizacijski workflow: SolidWorks → Visualize → marketing slika
