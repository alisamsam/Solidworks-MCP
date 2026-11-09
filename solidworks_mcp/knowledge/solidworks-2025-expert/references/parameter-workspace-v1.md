# Lokalna nadzorna plošča parametrov — specifikacija V1

Datum načrta: 25. 9. 2026. Obseg potrjen; prvi del implementiran 26. 9. 2026.
Ta dokument definira celotni V1. Trenutno so implementirani lokalni register,
spletna stran in dve MCP orodji registra; CAD adapterji in vse preostale
operacije tega načrta še niso izvedeni. Dejanski trenutni obseg in zagon določa
[operativna pogodba](parameter-workspace-operations.md).

## 1. Namen in merilo uspeha

Uporabnik na enem lokalnem spletnem mestu vidi konstrukcijske podatke projekta,
komu pripadajo, katere še potrebuje agent, kaj se izračuna in kaj lahko spremeni.
Spremembo vnese v obrazec ali kot besedilno zahtevo. Agent in obrazec delata
z istim registrom. Pri podprtih vezavah se model spremeni, obnovi in izmeri;
uporabnik vidi dejanski rezultat ter vpliv na povezane dele.

V1 je namenjen enemu uporabniku na lokalnem računalniku z več možnimi MCP
odjemalci. Ne zahteva določenega harnessa. Konstrukcijski primer za sprejem
je stopniščni sklop z ograjo; osnovni mehanizem mora delovati tudi za druge dele.

»Vsi parametri« pomeni vse evidentirane parametre in zahteve projekta ter
odkrite CAD parametre z jasno navedeno pokritostjo zajema. Ne pomeni zagotovila,
da poljuben uvožen model vsebuje konstrukcijsko namero ali popolno drevo funkcij.

## 2. Kaj V1 vključuje

- Trajen register projektov, lastnikov, parametrov, odvisnosti in zahtev.
- Drevo sestavov/delov/pojavitev in filtriranje po lastniku ter konfiguraciji.
- Trenutne CAD vrednosti, uporabnikove osnutke, manjkajoče podatke in izračune.
- Obrazce za številke, cela števila, izbire, besedilo in logične vrednosti.
- Pojasnila, izvor podatkov, merske reference, omejitve in skrite CAD vezave.
- Predogled sprememb, seznam prizadetih parametrov in komponent.
- Spremembe podprtih vhodnih mer/globalnih spremenljivk z obnovo in readbackom.
- Besedilne zahteve z izbranim kontekstom ter čakalno vrsto za agenta.
- Zgodovino, zaznavanje zastarelega stanja, ponovni priklop in izvoz registra.
- Začetne predloge za stopnice, ograje, pritrditve in pripravo za cinkanje.

V1 ne vključuje poljubnega izvajanja kode iz brskalnika, obljube splošnega
samodejnega spreminjanja vsake CAD funkcije, spletnega gostovanja, večuporabniških
vlog, učenja iz videoposnetkov ali SolidWorks add-in panela. Samodejno
spreminjanje topologije ostane ločena agentova naloga z načrtom in preverjanjem.

## 3. Arhitektura in lastništvo izvajanja

```text
Lokalni brskalnik ── HTTP ── Lokalna projektna storitev + register
                                      │
Poljuben MCP odjemalec ── MCP orodja ───┤
                                      │ tipizirane zahteve
                           En lastnik CAD povezave / delovna vrsta
                                      │
                         obstoječe varovanje + SolidWorks COM
```

Priporočilo za izvedbo: ločen lokalni Python proces, SQLite za trajne podatke,
statični spletni vmesnik brez zunanjih CDN in različican JSON API. Register je
skupen MCP procesom; ne nastane nova ločena kopija za vsak pogovor ali harness.
Za osveževanje V1 zadostuje kratko periodično preverjanje revizije z odmorom,
ko je zavihek skrit. Dostop do SolidWorksa ostane na niti, ki ima COM povezavo.

Spletni strežnik ne kliče COM iz poljubnih HTTP niti. Za delo brez agenta
mora storitev imeti svoj preverjeni CAD izvajalnik za podprte operacije.
Če ga ni ali ni povezan, sta pregled in urejanje osnutkov še vedno na voljo;
uporaba v CAD je onemogočena z razlogom. Zgolj dodajanje zahteve v vrsto ni
nadomestilo za delujoče izvajanje, kadar je GUI označen kot povezan.

Za celotno instanco SolidWorksa mora veljati ena izvajalna vrsta oziroma
medprocesna izključitev. Zaklep zgolj enega parta ne zadostuje, ker se aktivni
dokument spreminja. Neposredna CAD orodja MCP morajo sodelovati pri isti zaščiti.

Storitev posluša samo na loopback naslovu. Brskalnik dobi lokalno sejo;
API preverja sejo, Origin/Host in zaščito pred zahtevami tujih spletnih strani.
MCP povezava uporablja lokalno poverilnico, ki ni zapisana v izvozih ali logih.
Odjemalec ne določa poljubnih zapisovalnih poti, ukazov ali Python kode.

## 4. Projekt in identiteta lastnikov

Projekt ima stabilni UUID, naziv, verzijo sheme, revizijo registra, korenske
dokumente, izbrano predlogo, stanje povezave, čas zadnje sinhronizacije in
pravila shranjevanja. Vsak parameter ima `owner_id`, tudi pred nastankom CAD.

| Entiteta | Ključna polja in pomen |
|---|---|
| Lastnik | `owner_id`, vrsta, naziv, nadrejeni lastnik, načrtovan ali povezan |
| Dokument | `document_id`, vrsta part/assembly/drawing, kanonična pot ali začasna identiteta neshranjenega dokumenta |
| Pojavitev | `occurrence_id`, korenski sestav, celotna pot vstavitve, referenca na skupni dokument in uporabljeno konfiguracijo |
| Telo varjenca | Lastni ID znotraj dokumenta, veljavna referenca telesa/cut-list elementa; ni avtomatično samostojen part |
| CAD vezava | Ciljna konfiguracija, vrsta parametra, natančni selektor, izvor razrešitve, čas in stanje veljavnosti |
| Revizija | Revizija registra, posnetek CAD vrednosti in identitete; ločena podatka |

Prikaz za človeka: »Stopnice → Ograja → Levi steber«. Pot datoteke, tehnična
imena, ID in selektorji so pod »Podrobnosti«. Isti prikazni naziv ne pomeni
istega dokumenta. Preimenovanje, Save As, zamenjava komponente ali ponovno
odpiranje neshranjenega dokumenta sprožijo preverjanje vezave, ne tihega prenosa.

Parameter dokumenta je skupen njegovim pojavnostim v isti konfiguraciji.
Parameter položaja/vezi lahko pripada pojavitvi v sestavu. GUI mora razlikovati
»spremeni ta part« od »spremeni položaj te vstavitve«. Izbira pojavitve sama
po sebi ne omogoči neodvisne spremembe njene skupne geometrije.

## 5. Pogodba parametra

| Skupina | Zahtevani podatki |
|---|---|
| Identiteta | `parameter_id`, `owner_id`, ključ, naziv, skupina, opis |
| Vrednosti | `observed_value`, `draft_value`, izračunani predlog, čas opažanja; null pomeni manjka, 0 je veljavna vrednost |
| Tip in enote | number/integer/boolean/enum/text, fizikalna količina, enota vnosa in notranja enota, natančnost prikaza |
| Referenca mere | Izhodišče, smer merjenja, končne ali surove površine; po potrebi vezana skica/shema |
| Vloga | Vhod, izračun, meritev, omejitev ali metapodatek |
| Izvor | Uporabnik, prebrano iz CAD, izračun, dokument z lokacijo, predloga ali predpostavka |
| Zahtevanost | Ali blokira naslednji korak in pri katerem pogoju je obvezen |
| Pravila | Meje, možnosti, pogojna veljavnost, izvor in stopnja pravila (obvezno/priporočilo) |
| Odvisnosti | ID vhodov, deklarativna formula in enote; seznam prizadetih parametrov |
| CAD vezava | Dokument, pojavitev po potrebi, konfiguracija, selektor, obseg spremembe, zmožnost adapterja |
| Razpoložljivost | Berljivost, urejanje osnutka, zapisljivost v CAD, razlog omejitve |
| Dokaz | Zadnja preverjena vrednost, metoda, operacija, opozorila in stanje vezave |

Ne združi vseh stanj v eno oznako. Ločeno hrani:
- popolnost: manjka / predpostavka / podano;
- vezavo: načrtovana / veljavna / zastarela / izgubljena;
- osnutek: nespremenjen / spremenjen / konflikt;
- izvedljivost: podprto / samo branje / nepodprto;
- preverjanje: nepreverjeno / ustreza / napaka.

V UI pokaži kombinacijo, ki pojasni naslednji korak, npr. »Vrednost podana;
CAD vezava še manjka«. Izračun ni sinonim za manjkajoč podatek.

## 6. Izračuni in konstrukcijske odvisnosti

Formula uporablja stabilne ID parametrov in omejen nabor operacij, ne `eval`
poljubnega besedila. Izvajalec preveri cikle, manjkajoče vhode, deljenje z nič,
neveljavne številke in skladnost fizikalnih količin. Izračun se izvede tudi
na strežniku. Decimalno vejico pri slovenskem vnosu normalizira nedvoumno.

Graf naj bo usmerjen in brez ciklov. Če ima CAD svojo enačbo, jo prikažemo z
izvorom; ne ustvarimo dveh neodvisnih avtoritet za isto mero. Nepodprta enačba
se lahko pokaže kot besedilo, vendar je lastni izvajalec ne označi kot preverjeno.
Zaokroževanje prikaza ne spremeni shranjene vrednosti ali konstrukcije.

Izračunan parameter je privzeto samo za branje z ukazom »Pokaži vhode«.
Želena izhodna vrednost je lahko nova zahteva agentu, ne tiha odstranitev enačbe.
Numerični rezultat ne potrjuje nosilnosti ali skladnosti s predpisom.

## 7. Uporabniški vmesnik

Tri glavna področja: levo drevo projekta, sredina parametri izbranega lastnika,
desno zložljiv pregled sprememb in zahtev. Na vrhu projekt, konfiguracija,
povezava in zadnja sinhronizacija. Prikaz mora delovati tudi v ožjem oknu.

Filtri: vsi, potrebujem odgovor, spremenjeno, izračunano, konflikt/neveljavno,
samo za branje; iskanje po nazivu in poti lastnika. Filter lastnika vključuje
možnost »vključi podrejene«. Privzeto pokaži konstrukcijsko pomembne parametre,
v naprednem pogledu vse odkrite tehnične parametre. Vedno povej obseg zajema.

Vrstica parametra: naziv, lastnik, trenutna vrednost, urejevalnik predloga,
enota, stanje in kratka razlaga. Podrobnosti razkrijejo izvor, odvisnosti in
CAD referenco. Povezave na odvisne parametre odprejo pravo vrstico v drevesu.
Oznake imajo besedilo, ne samo barve. Polja so dostopna s tipkovnico in labelami.

Dejanja:
- »Osveži iz modela«: prebere stanje brez prepisovanja osnutkov;
- »Shrani osnutek«: shrani register, ne CAD datoteke;
- »Preveri spremembe«: validacija, odvisnosti, prizadeti deli in opozorila;
- »Uporabi v SolidWorksu«: samo preverjene podprte spremembe;
- »Zavrzi osnutek«: samo izbrane še neizvedene spremembe;
- »Oddaj zahtevo agentu«: shrani besedilo s kontekstom in sledljivim statusom;
- »Izvozi register«: različican JSON z izvorom in stanji, brez poverilnic.

Uvoz registra preveri shemo in konflikte ter ne izvede CAD sprememb. Uvožene
reference so nepreverjene, dokler niso ponovno razrešene. Predogled modela je
opcijski; prikaz zadnje slike vsebuje čas, shema pa oznako, da ni CAD meritev.

## 8. Spremembe in okrevanje

Vsak paket ima ID, avtorja (uporabnik/agent), projektno revizijo, stare in nove
vrednosti, ciljne dokumente/konfiguracije, pričakovano CAD stanje in obseg.
Ponovitev istega ID z enako vsebino vrne obstoječi rezultat; druga vsebina z
istim ID se zavrne. Zagon paketa zahteva izključno pravico do CAD izvajalnika.

Potek: osnutek → validiran → v čakalni vrsti → izvaja se → preverjen / neuspešen
/ delno izveden / potrebno ponovno preverjanje. Osnutek je urejevalno stanje;
že oddani paket je nespremenljiv. Sprememba vnosa pripravi nov paket.

Pred zapisom se ponovno preverijo cilj, konfiguracija, selektorji in stare
CAD vrednosti. Obstoječi MCP revision token zazna samo lastne znane spremembe;
ni zadosten dokaz, da uporabnik ni ročno popravil modela. Potreben je svež
posnetek vrednosti in pomembnih odvisnosti oziroma preverjena revizija CAD.

Paket se v celoti preveri pred prvo mutacijo. Zatem se izvajajo podprte
operacije v vrstnem redu odvisnosti, obnova, branje nazaj in kontrola napak.
Napaka prekine odvisne korake. Vrnitev na prejšnje stanje ni zajamčena transakcija
COM: navede se dejanski rezultat vsakega koraka, možna obnova in preostali problem.

Po prekinitvi procesa paket »izvaja se« preide v potrebno ponovno preverjanje;
ne ponovi se slepo. Preklic pred začetkom je zagotovljen; med izvajanjem pomeni
ustavitev pred naslednjim varnim korakom, ne obljube prekinitve sredi COM klica.
Vrnitev stare vrednosti je nov preverjen paket. Shranjevanje CAD datotek je
ločeno od uspešne spremembe modela in spoštuje projektno politiko.

## 9. Agentove zahteve in trajno znanje

Zahteva vsebuje besedilo, izbrane lastnike/parametre, posnetek konteksta, čas
in ID. Statusi: čaka na agenta, prevzeta, potrebno pojasnilo, pripravljen predlog,
izvedena, zavrnjena, preklicana. Prevzem ima lastnika in veljavnost; dve seji
ne smeta hkrati izvesti iste zahteve. Potek veljavnosti ne ponovi nejasne CAD mutacije.

Harness brez možnosti samodejnega spremljanja vrste jo preveri ob naslednjem
klicu; UI pošteno pokaže »čaka na agenta«. Lokalna stran ne obljublja, da lahko
sama zbudi poljuben agent. Podprte deterministične spremembe skozi obrazec
pa naj ne potrebujejo jezikovnega modela.

Odgovor na manjkajoči podatek in izvedena CAD sprememba sta ločena dogodka.
Agentovi popravki ohranijo uporabnikov vnos, razlog in dokaze. Novo splošno
pravilo konstrukterske baze potrebuje določen obseg in preverjanje; projektne
posebnosti se ne širijo samodejno v vse projekte. V1 ne trenira modela.

## 10. Začetne domenske predloge

Predloge določajo vprašanja in odvisnosti; niso univerzalne standardne mere.

| Predloga | Primer vhodov | Odvisnosti in dodatna preverjanja |
|---|---|---|
| Stopnice | Končna višina etaž, razpoložljiv prostor, širina, topologija, podesti, število višin, zaključni sloji | Višine in nastopi glede na topologijo, naklon, povezava na ograjo; manjkajoče izmere blokirajo izvedbo |
| Ograja | Referenca višine, dolžina/potek, profili, polnilo, pritrditve | Prehodi ob podestih, odmiki, stebri in povezava na aktualno geometrijo stopnic |
| Pritrditev | Podlaga, dostop za montažo, plošče, sidra, robni pogoji | Prostor za montažo, kolizije, potreba po konstrukcijskem izračunu; brez izmišljene nosilnosti |
| Izdelava | Material, varjenje, delitev sklopov, površinska obdelava | Zaporedje izdelave, transport, dostopnost obdelave in prevleka |
| Cinkanje | Izbrani izvajalec/navodila, votli deli, orientacija, delitev | Odzračevanje in iztok z virom in geometrijskim preverjanjem; ne avtomatična oznaka skladnosti |

Uporabnikovi PDF in priročniki ostajajo viri pravil; datum in konkretno mesto
vira se zapišeta ob pravilu. Vrednosti iz predloge so predlogi, dokler niso
potrjene za projekt. Zahtevana zakonska ali standardna meja mora imeti
preverjen vir in ustrezno področje uporabe.

## 11. Predlagani vmesniki — še niso obstoječa MCP orodja

HTTP in MCP uporabljata iste aplikacijske operacije, validacijo in revizije.
Imena spodaj so predlog pogodbe, ne imena za takojšnje klicanje.

| Operacija | Vhod → rezultat |
|---|---|
| Odpri projektno ploščo | Projekt → lokalni URL in ločeno stanje registra/CAD izvajalnika |
| Preberi register | Projekt, lastnik, filtri, straničenje → parametri, revizija, pokritost zajema |
| Sinhroniziraj model | Ciljni dokumenti/obseg → odkrite vrednosti, spremembe vezav, omejitve zajema |
| Dopolni register | Pričakovana revizija + tipizirane definicije/vrednosti → nova revizija ali konflikt |
| Preveri paket | Predlagane spremembe → napake, izračuni, vpliv, podprte operacije |
| Oddaj paket | Validiran paket + pričakovano stanje → ID izvedbe, ne lažen takojšnji uspeh |
| Preberi/prekliči izvedbo | ID → status, rezultat vsakega koraka in dokaz |
| Oddaj/prevzemi zahtevo | Besedilo + kontekst / ID odjemalca → sledljivo opravilo |
| Preberi zgodovino | Projekt/parameter + kazalec strani → dogodki in razlogi |
| Izvozi/uvozi register | Verzija sheme + vsebina → prenos oziroma validiran osnutek |

Branje ne poveže ali zažene SolidWorksa brez razloga. Zapis registra ni CAD
mutacija in potrebuje jasno ločeno klasifikacijo v strežniku. Operacije CAD
ohranijo obstoječe varovanje dokumentov, dovoljenih poti in operation ID.
Zavrnitev vrne stabilno kodo in uporabniku razumljiv razlog (npr. konflikt
revizije, izgubljena vezava, neveljavna enota, nepodprta sprememba).

## 12. Kaj lahko ponovno uporabimo in kaj manjka

Pregled lokalne kode ob pripravi:
- `workspace/parameters.py`: preverjanje pričakovane revizije in stare vrednosti;
  potrebuje razširitev za tipe, enote, duplicate, konfiguracije in paketni tok.
- `workspace/selectors.py`: natančno razreševanje reference z instance path;
  uporabno za vezave, vendar ne nadomesti svežega zajema SolidWorks podatkov.
- `core/session.py`: vezava cilja in MCP revizije; ni zaznavanje vseh ročnih sprememb.
- `knowledge/`: skupna dokumentacija za skill in MCP; ni spletni izvajalnik.
- `add_equation`: dodajanje spremenljivke; ni generični zapis obstoječe enačbe.

Manjkajo trajni register, lokalni strežnik, spletni UI, medprocesno usklajevanje,
zanesljiv popis in adapterji za spremembe obstoječih parametrov z živo verifikacijo.
Podpora se objavlja po vrsti parametra in adapterju, ne kot en sam »CAD deluje«.

## 13. Sprejemni preizkusi V1

| Scenarij | Zahtevan rezultat |
|---|---|
| Nov projekt brez SolidWorksa | Vnos zahtev, osnutek in ponovni zagon ohranijo podatke; CAD jasno nepovezan |
| Dva različna MCP odjemalca | Vidita isti projekt in revizijo, brez podvojenih storitev/registra |
| Dve pojavitvi istega parta | Pravilno razločen skupni parameter in prikazan vpliv na obe pojavitvi |
| Enako ime v dveh dokumentih | Nobeno razreševanje samo po prikaznem imenu |
| Različni konfiguraciji | Spreminja se samo izrecno izbrani podprti obseg |
| Neshranjen ali preimenovan model | Vezava se preveri; napačen cilj se zavrne pred mutacijo |
| Ročna sprememba med odprtim obrazcem | Konflikt brez prepisovanja modela ali uporabnikovega osnutka |
| Ničla, prazno, decimalna vejica, mm/m | Pravilna semantika in pretvorba; neveljavni vnosi zavrnjeni na strežniku |
| Cikel, manjkajoč vhod, deljenje z nič | Razumljiva napaka brez lažnega izračuna ali CAD zapisa |
| Dvojni klik in sočasni agent | En paket se izvede enkrat, CAD mutacije so serializirane |
| Izpad po prvem zapisu | Delno/neznano stanje in ponovno preverjanje; brez slepega ponavljanja |
| Živa sprememba scratch dela | Prebrane mere in geometrija ustrezajo; izvirni projekti ostanejo nedotaknjeni |
| Stopnice in povezana ograja | Sprememba vhodov pokaže odvisnosti; podprte mere so po obnovi preverjene |
| Zahteva brez aktivnega agenta | Ostane vidno čakajoča; ni lažne potrditve izvedbe |
| Uvoz in zunanji spletni izvor | Uvoz ne mutira CAD; tuje spletne zahteve in poljubna koda so zavrnjene |
| Večji sestav | Začetni plitki zajem, nalaganje vej na zahtevo, merjen odziv brez COM klica na vsako tipko |

V1 je končan šele po preizkusu celotnega kroga v brskalniku in na poskusnem
CAD modelu. Uspešni testi registra ali prikaz obrazca ne zadostujejo.

## 14. Predlagano zaporedje izvedbe

1. Register, identiteta lastnikov, revizije, podatkovna validacija in trajnost.
2. Spletni pregled, obrazci, filtri, skrite reference in zgodovina osnutkov.
3. MCP dostop do istega registra, vrsta zahtev in medprocesno usklajevanje.
4. Zajem/vezava CAD parametrov in omejen preverjen adapter zapis–obnova–readback.
5. Izračuni, vpliv sprememb in domenske predloge stopnic/ograj/izdelave.
6. Celotni sprejemni preizkusi, dokumentacija zagona in poročilo o omejitvah.

Vsaka stopnja ima preverljiv rezultat; šele skupni sprejemni preizkus dovoljuje
oznako »povezana V1«. Pred izvedbo se uporabniku predstavi ta specifikacija,
nato se napiše datotečno natančen izvedbeni načrt. Ta dokument ni tak načrt.
