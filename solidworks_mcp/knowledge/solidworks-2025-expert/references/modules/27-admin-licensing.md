# 27 Admin & Licensing — navodila za obdelavo

## Kaj poudariti

- **Installation Manager** — SWova aplikacija za namestitev, posodobitev in remove
- **Individual Installation** — namestitev na en računalnik
- **Administrative Image** — centralizirana namestitev za IT oddelke (tiha namestitev)
- **License Types**: Standalone (vezana na en računalnik), Network (plavajoča, SNL Manager)
- **SolidNetWork License (SNL) Manager** — strežnik za omrežne licence
- **Add-in Management** — vklop/izklop modulov (Simulation, CAM, Routing, PDM...)
- **Izklop neuporabljenih modulov** za hitrejši zagon in boljši performance
- **Service Packs** — posodobitveni paketi (SP1, SP2, SP3...)
- **Upgrade na SW 2025** — potek, backup, kompatibilnost
- **Hardware Requirements** — minimalne in priporočene specifikacije
- **Certified Graphics Cards** — seznam certificiranih kart
- **Performance Settings** — RealView, anti-aliasing, Heads-up View Toolbar, Detailing Mode
- **File Locations** — poti za templates, Toolbox, weldment profiles, sheet formats, custom symbols
- **Templates / Library Locations** — centralizacija za timsko delo
- **Backup nastavitev** — Copy Settings Wizard za varnostno kopijo vseh nastavitev
- **Copy Settings Wizard** — prenos nastavitev med računalniki ali po upgradu
- **Stability Best Practices** — stabilna konfiguracija okolja

## Obvezne usmeritve

- Pri **add-in management** razloži vpliv na zagon in performance:
  - Vsak vklopljen add-in poveča čas zagona in porabo RAM
  - Priporoča se vklop samo add-inov, ki jih ekipa dejansko uporablja
  - Pogoste napake: Routing add-in vklopljen, čeprav se ne gebruikt → upočasni vsak zagon
- Pri **file locations** razloži pomen pravilnih poti:
  - Templates: `Tools > Options > System Options > File Locations > Document Templates`
  - Toolbox: mora kazati na skupno lokacijo (ne lokalni disk, ko delamo timsko)
  - Weldment Profiles: pot do knjižnice profilov (SWdefault ali custom)
  - Sheet Formats: pot do sheet format datotek za risbe
  - Napačne poti → "file not found" napake, napačni formati, manjkajoče predloge
- Pri **upgrade** razloži:
  - Pred upgradOM: obvezni backup nastavitev (Copy Settings Wizard)
  - Po upgradu: preveriti kompatibilnost modelov (SW ponudi samodejno posodobitev featurejev)
  - Priporoča se testni upgrade na testni namestitvi pred produkcijo
- Pri **hardware** razloži pomen certificirane grafične kartice:
  - RealView, anti-aliasing in stabilnost OpenGL slike zahtevajo certificiran gonilnik
  - Necertificirana kartica (gaming GPU brez delovnih gonilnikov) pogosto povzroča padce prikaza, napake v OpenGL
  - Preveriti: https://www.solidworks.com/support/hardware-certification/
- Pri **izklopu modulov** jasno navedi, kateri so **izključeni v tem projektu**:
  - Flow Simulation, Plastics, Electrical, PDM, Manage, eDrawings, 3DEXPERIENCE
- Pri **Copy Settings Wizard** razloži:
  - Shranjuje vse System Options, CommandManager, moje orodne vrstice, barvne sheme
  - Bistveno pri prehodu na nov računalnik ali po reinstalaciji

## Tipični primeri podtem

- Installation Manager (namestitev, popravilo, odstranitev)
- Standalone vs. Network License
- SNL Manager konfiguracija
- Add-in vklop/izklop
- Service Pack posodobitev
- Upgrade na SW 2025
- Hardware Requirements in Graphics Certification
- Performance nastavitve (RealView, Detail Mode)
- File Locations (Templates, Toolbox, Weldment, Sheet Formats)
- Copy Settings Wizard
- Backup strategija
- Multi-user brez PDM (skupne mrežne lokacije)
