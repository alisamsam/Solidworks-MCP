# 14 Motion — navodila za obdelavo

## Kaj poudariti

- **Animation** — vizualni prikaz gibanja brez fizikalne analize
- **Basic Motion** — poenostavljena fizikalna simulacija (motor, sila, gravitacija)
- **Motion Analysis** — polna dinamična simulacija s silami, masi, trki, momenti
- **Mates in motion** — kako mates (sestava) nadzirajo gibanje
- **Motors** — rotacijski in linearni motorji (konstantna hitrost, oskar, profil)
- **Forces** — zunanja sila ali navor aplikirana na telo
- **Springs** — linearne in torzijske vzmeti
- **Dampers** — dušilci za realistično simulacijo odziva
- **Gravity** — gravitacijski pospešek v definirani smeri
- **Contacts** — trki med komponentami (3D contact, elastic, inelastic)
- **Motion Results** — grafični prikaz pomika, hitrosti, pospeška, sile, momenta

## Obvezne usmeritve

- Razloži razliko med **animacijo in fizikalno analizo**:
  - **Animation**: komponente premikamo z ročno definiranimi interpolacijami — brez fizike
  - **Basic Motion**: preprosta fizika (masa, trk, motor) — orientativna, ne za inženirske izračune
  - **Motion Analysis**: polna dinamika (MBS — Multi-Body Simulation) — rezultati so inženirsko zanesljivi
- Pri **motors** razloži:
  - **Rotational Motor**: vrti os (tipično ležaj, os motorja)
  - **Linear Motor**: premika komponento po ravni liniji (tipično cilinder, pnevmatski bat)
  - Profil motorja (velocity, acceleration, expression) definira gibalni zakon
- Pri **contacts** razloži:
  - 3D kontakt je računsko zahteven — poveča čas simulacije
  - Preveč kontaktov = simulacija se upočasni ali zamrzne
  - Priporoči selektivno kontaktno definicijo samo tam, kjer je fizično potrebno
- Pri **rezultatih** razloži:
  - Grafični prikaz: časovni diagram pomika, hitrosti, pospeška, sile, momenta
  - Posamezni točki ali telesu se sledita z markerjem (Plot Results)
  - Rezultate je mogoče izvoziti v CSV za nadaljnjo analizo
- Posebej opozori: **sestav mora biti pravilno pripravljen** — prekomerno omejen ali nedefinirani mates bodo preprečili pravilno simulacijo gibanja

## Tipični primeri podtem

- Animation (ConstraintManager, MotionManager, timeline)
- Basic Motion (motor, gravitacija, sila)
- Motion Analysis (MBS, connector, contact)
- Motors (rotational, linear, expression-driven)
- Forces in Torques
- Springs in Dampers
- Gravity
- 3D Contact
- Motion Results (plot, animacija, CSV export)
- Kinematična analiza mehanizma
