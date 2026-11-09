# 15 CAM — navodila za obdelavo

## Kaj poudariti

- **CAM Standard vs. CAM Professional** — razlike v zmogljivostih (3-osno vs. večosno)
- **Machine Definition** — definicija stroja (freza, stružnica, osi, hod)
- **Stock Definition** — dimenzije in oblika surovca
- **Coordinate Systems** — koordinatni sistem CAM-a (ničelna točka programa)
- **Feature Recognition (AFR)** — samodejno prepoznavanje obdelovalnih elementov
- **Interactive Feature Creation (IFC)** — ročno definiranje obdelovalnih elementov
- **Operation Plan** — zaporedje operacij (roughing, semi-finishing, finishing)
- **Technology Database (TechDB)** — standardizirane obdelovalne strategije
- **Tool Library** — knjižnica orodij (premer, material, parametri rezanja)
- **2.5-axis milling** — konturiranje, žepkanje, vrtanje v 2.5D
- **Pocketing** — izrezkovanje žepov
- **Contouring** — obris kosa
- **Drilling / Tapping** — vrtanje in navrezovanje
- **Turning** — struženje (samo pri ustrezni licenci — preveriti)
- **Toolpath Generation** — izračun poti orodja
- **Toolpath Simulation** — vizualna simulacija (verifikacija trkov, presezkov)
- **Post Processing** — pretvorba poti v G-kodo za konkreten stroj
- **G-code Export** — izvoz NC programa

## Obvezne usmeritve

- Pri vsaki CAM podtemi razloži **varnostni vidik**:
  - Napaka v G-kodi = trk orodja s kosom, vpenjalom ali strojem
  - G-kode ni dovoljeno prenesti na stroj brez pregleda in simulacije
- Pri **coordinate system** razloži pomen ničelne točke:
  - Ničelna točka CAM-a (WCS/WZP) mora biti enaka ničelni točki na stroju
  - Napaka v postavljanju ničle = premaknjeno obdelovanje ali trk
- Pri **post processing** opozori:
  - Postprocesor mora biti usklajen s konkretnim strojem in krmiljem (Heidenhain, Fanuc, Siemens...)
  - Postprocesor za en stroj ne deluje za drugi brez prilagoditve
- Pri **G-code export** opozori:
  - Preden prenesemo kodo na stroj: obvezna vizualna simulacija + pregled NC izpisa
  - Ni alternative za pregled kode — simulacija v CAM-u ≠ realno obnašanje na stroju
- Pri **TechDB (Technology Database)** razloži pomen standardiziranih obdelovalnih pravil:
  - TechDB shranjuje tipične parametre rezanja za material+orodje kombinacijo
  - Z urejevanjem TechDB organizacija standardizira in pospeši pripravo CAM programov
- Pri **turning** opozori: dostopnost struženja je odvisna od licence (Standard vs. Professional vs. CAM for Turning add-in)

## Tipični primeri podtem

- Machine Definition
- Stock Definition
- Coordinate Systems (WCS/WZP)
- Automatic Feature Recognition (AFR)
- Interactive Feature Creation (IFC)
- 2.5-axis Milling (contouring, pocketing)
- Drilling in Tapping
- Roughing Strategies
- Finishing Strategies
- Tool Library Management
- Technology Database (TechDB)
- Toolpath Simulation
- Post Processor Management
- G-code Export in pregled
- Operation Plan
