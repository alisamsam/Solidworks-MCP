# Prilagajanje obstoječega projekta: najprej neodvisna kopija

Privzeta uporabnikova namera je nov projekt na podlagi prejšnjega. Izvirnih
komponent ne spreminjaj. Izrecno naročilo urejanja izvirnika je druga namera;
argument `edit_original=true` ne obide zaščitenih poti strežnika.

## Kopiranje

1. Z `inspect_project_references(source_path, drawings?, include_drawings=true)`
   preberi shranjene neposredne in rekurzivne CAD reference. Povezane risbe se
   iščejo pod mapo izvornega dokumenta. Risbe iz drugih map navedi v `drawings`;
   samodejno iskanje po celotnem disku ni vključeno. Nepodprti/manjkajoči
   dokumenti preprečijo kopiranje. Poljubni spremljevalni PDF, slike in Excel
   datoteke se ne kopirajo samodejno. Zunanje enačbene datoteke/profili zahtevajo
   posebej preverjeno podporo; manjkajoče podpore ne označi kot popoln prenos.
2. `copy_project(source_path, destination_folder, drawings?, include_drawings=true)`
   zahteva še neobstoječo mapo znotraj dovoljenega izhodnega korena. Kopira
   dosegljive native dokumente, vsaki kopiji dodeli nova enolična imena, preusmeri
   reference samo v zaprtih kopijah ter preveri reference in SHA256 izvirnikov.
   Neshranjene spremembe izvora zavrne; izvirnika ne shrani samodejno.
3. Preberi rezultat. Samo `status=verified` pomeni pripravljeno kopijo.
   `failed` mapa je delni rezultat, ki ga ne uporabljaj za urejanje. Ne ponavljaj
   na isti poti ali briši delne mape tiho. Izberi novo mapo po razrešitvi vzroka.
4. Odpri vrnjeni `root_document` in ponovno veži aktivni dokument. Ne odpiraj
   ročno domnevane poti s starim imenom; kopija ima drugačno ime. Osveži
   `list_components` in `list_model_parameters`.

Shrani kot (Save As) na sestavu ni neodvisen projekt: kopija sestava še vedno
kaže na izvirne dele. Neodvisen projekt nastane samo s `copy_project` in
preverjenim manifestom.

## Spreminjanje obstoječega dela

`list_model_parameters()` bere dimenzije funkcij in skic ter enačbe/globalne
spremenljivke. `complete=false` in `unresolved` pomenita nepopoln pregled.
Skrite ali nedostopne mere niso izmišljene. Uporabi dejansko vrnjeno ime mere.

`set_model_dimension(name, value, unit, expected_value, configuration)`
spremeni krmilno mero samo v trenutno aktivni konfiguraciji. Konfiguracijo
in staro vrednost je treba najprej prebrati. Enote so izrecne: mm/cm/m/in/ft,
deg/rad oziroma scalar za celoštevilske parametre. Read-only, driven in
enačbeno krmiljeno mero zavrne. Po zapisu preveri rebuild, napake glavnih
funkcij in vrednost nazaj. Uspešen rezultat ne pomeni shranjene datoteke ali
celovite potrditve konstrukcijskih pravil.

Sprememba geometrije parta v isti konfiguraciji vpliva na vse njegove
pojavitve. Če uporabnik želi drugačno geometrijo samo enega stebra:

1. `copy_project` za obstoječi kopirani part v novo ločeno izhodno mapo;
   pri tej posamični kopiji uporabi `include_drawings=false`, če risbe niso del
   naloge. Nova komponenta mora prav tako imeti preverjen manifest.
2. V kopiranem sestavu pokliči
   `replace_component(component_name, replacement_path, expected_path, configuration)`.
   Ime pojavitve mora biti točno `Name2`, brez približnega iskanja. Privzeto
   zamenja samo izbrano pojavitev; `all_instances=true` je izrecna odločitev.
   Za globoko pojavitev najprej aktiviraj njen neposredno nadrejeni podsestav.
   Zahtevana konfiguracija mora obstajati tudi v nadomestnem partu.
3. Odpri novo komponento, preberi mere in jo prilagodi. Nato preveri položaj,
   povezave in namen vezi v sestavu. Orodje preveri poti, obseg in rebuild;
   avtomatska pravilna ponovna pritrditev vseh vezi ni obljubljena.

Pred urejanjem se preverijo tudi reference odprtih dokumentov. Ločena
preverjena kopija komponente je dovoljena; referenca na izvirni part ni.
Virtualne/nedoločene komponente se zavrnejo, če izolacije ni mogoče dokazati.

## Enačbe in predaja

`update_model_equation(index, rhs, expected_expression, configuration)`
ohrani levo stran obstoječe enačbe, preveri staro besedilo, spremeni desno
stran ter preveri ovrednotenje in obnovo. Ne nadomesti ga z `add_equation`,
ker dodajanje nove spremenljivke ni urejanje obstoječe.

Status 26. 9. 2026: kopiranje, branje mer, sprememba mere in posamična
zamenjava so preverjeni na izoliranem živem vzorcu SW 2025 33.1.1. Urejanje
enačb je pokrito z unit testi in podpisom lokalne tipne knjižnice, še ni živo
potrjeno; `add_equation` je pri pripravi tega vzorca vračal -1. Ne trdi, da
je ta del že preverjen na resničnem projektu. Več konfiguracij, kompleksne
vezi, virtualne komponente in risbe potrebujejo dodatne žive primere.

Ob napaki z `document_may_be_modified=true` je dokument lahko že spremenjen.
Ne ponavljaj mutacije slepo. Ponovno preberi stanje; samodejne povrnitve ni.
Po preverjanju uporabnikovih zahtevanih sprememb shrani samo datoteke kopije.
Celoten projekt ima lahko več preverjenih map komponent; pri predaji ohrani
vse uporabljene mape in ponovno preveri reference.

Ta orodja so samostojni MCP vmesnik. Spletni register parametrov jih še ne
uporablja kot samodejni adapter: osnutek v GUI še vedno ne spremeni CAD.
